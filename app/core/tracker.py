"""Ядро отслеживания: планировщик проверок и матчинг по цене/льготам.

Логика «тика»:
  1. удалить отслеживания с прошедшей датой вылета;
  2. для каждого активного отслеживания, у которого истёк его интервал проверки,
     опросить включённые провайдеры и собрать офферы;
  3. если найден билет дешевле порога и дешевле, чем в прошлый раз — уведомить.

Один периодический job (APScheduler) сканирует все отслеживания и сам решает,
какие пора проверять. Это проще и надёжнее, чем держать отдельный job на каждое
отслеживание.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import AppConfig
from app.db.models import Tracking
from app.db.repository import TrackingRepository
from app.notifications import Notifier
from app.providers import (
    BaseProvider,
    CityResolver,
    FlightOffer,
    SearchQuery,
    build_enabled_providers,
)

logger = logging.getLogger(__name__)
# Отдельный логгер результатов поиска (настраивается в main.setup_search_logging).
search_logger = logging.getLogger("search")


class Tracker:
    def __init__(
        self,
        config: AppConfig,
        repository: TrackingRepository,
        notifier: Notifier,
        resolver: CityResolver | None = None,
        log_searches: bool = False,
    ) -> None:
        self._config = config
        self._repo = repository
        self._notifier = notifier
        self._log_searches = log_searches
        self._providers: list[BaseProvider] = build_enabled_providers(
            config.providers, resolver
        )
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        if not self._providers:
            logger.warning(
                "Нет активных провайдеров — проверки не дадут результатов. "
                "Проверь providers.enabled в setup.yaml."
            )
        interval = self._config.scheduler.min_interval_minutes
        self._scheduler.add_job(
            self.tick,
            trigger="interval",
            minutes=interval,
            id="tracking_tick",
            next_run_time=datetime.now(timezone.utc),  # первый прогон сразу
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info("Планировщик запущен, тик каждые %s мин", interval)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def tick(self) -> None:
        """Один проход планировщика по всем отслеживаниям."""
        today = date.today()
        removed = await self._repo.delete_expired(today)
        if removed:
            logger.info("Удалено отслеживаний с прошедшей датой: %s", removed)

        trackings = await self._repo.list_active()
        now = datetime.now(timezone.utc)
        due = [t for t in trackings if self._is_due(t, now)]
        if not due:
            return

        logger.info("К проверке готово отслеживаний: %s", len(due))
        for tracking in due:
            await self._check_one(tracking)

    @staticmethod
    def _is_due(tracking: Tracking, now: datetime) -> bool:
        if tracking.last_checked_at is None:
            return True
        last = tracking.last_checked_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return now - last >= timedelta(minutes=tracking.check_interval_minutes)

    async def _check_one(self, tracking: Tracking) -> None:
        query = SearchQuery(
            origin=tracking.origin,
            destination=tracking.destination,
            departure_date=tracking.departure_date,
            max_price=tracking.max_price,
            benefit=tracking.benefit_category,
            currency=tracking.currency,
        )

        # Опрашиваем все провайдеры параллельно.
        results = await asyncio.gather(
            *(provider.safe_search(query) for provider in self._providers)
        )

        if self._log_searches:
            for provider, batch in zip(self._providers, results):
                self._log_search(provider, query, batch)

        offers: list[FlightOffer] = [offer for batch in results for offer in batch]

        # Подходящие — дешевле порога.
        affordable = [o for o in offers if o.price <= tracking.max_price]
        if not affordable:
            await self._repo.mark_checked(tracking.id)
            return

        best = min(affordable, key=lambda o: o.price)

        # Уведомляем, только если цена ниже, чем при прошлом уведомлении
        # (или уведомления ещё не было) — чтобы не спамить.
        previous = tracking.last_notified_price
        if previous is not None and best.price >= previous:
            await self._repo.mark_checked(tracking.id)
            return

        await self._notifier.notify_offer(tracking, best)
        await self._repo.mark_checked(tracking.id, notified_price=best.price)
        logger.info(
            "Уведомление отправлено: tracking=%s цена=%s", tracking.id, best.price
        )

    @staticmethod
    def _log_search(
        provider: BaseProvider, query: SearchQuery, offers: list[FlightOffer]
    ) -> None:
        """Пишет результат одного похода на сайт в лог поисков."""
        route = f"{query.origin}→{query.destination}"
        head = (
            f"{provider.display_name} | {route} | {query.departure_date} | "
            f"{query.benefit.label}"
        )
        if not offers:
            search_logger.info("%s | офферов: 0", head)
            return
        min_price = min(o.price for o in offers)
        lines = [f"{head} | офферов: {len(offers)} | мин. цена: {min_price:.0f} {query.currency}"]
        for offer in offers:
            extra = f" · {offer.details}" if offer.details else ""
            lines.append(f"    - {offer.price:.0f} {offer.currency}{extra}")
        search_logger.info("\n".join(lines))
