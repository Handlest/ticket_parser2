"""Базовый интерфейс провайдера-сайта.

Чтобы добавить новый сайт (S7, RedWing, Аэрофлот, ...), достаточно:
  1. создать файл в app/providers/,
  2. унаследоваться от BaseProvider и реализовать search(),
  3. зарегистрировать класс декоратором @register.

Ядро приложения и Telegram-бот при этом не меняются.
См. docs/providers.md.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.config import ProvidersConfig
from app.domain.benefits import BenefitCategory
from app.providers.models import FlightOffer, SearchQuery

if TYPE_CHECKING:
    from app.providers.s7_locations import CityResolver

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    #: Уникальное имя провайдера. Используется в setup.yaml (providers.enabled).
    name: str = ""

    #: Человекочитаемое название (для уведомлений и логов).
    display_name: str = ""

    def __init__(
        self, config: ProvidersConfig, resolver: "CityResolver | None" = None
    ) -> None:
        self.config = config
        # Резолвер «город → IATA-код» с кэшем в БД. Нужен не всем провайдерам,
        # поэтому необязателен (см. app/providers/s7_locations.py).
        self.resolver = resolver

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[FlightOffer]:
        """Ищет билеты по запросу и возвращает список офферов.

        Реализация НЕ должна пробрасывать исключения наружу из-за сетевых или
        парсинговых ошибок — лучше залогировать и вернуть пустой список. За это
        отвечает safe_search() ниже, который ядро и вызывает.
        """
        raise NotImplementedError

    def supports_benefit(self, benefit: BenefitCategory) -> bool:
        """Поддерживает ли провайдер данную категорию льгот.

        По умолчанию — поддерживает любую (включая NONE). Переопредели, если
        сайт умеет искать только обычные билеты.
        """
        return True

    async def safe_search(self, query: SearchQuery) -> list[FlightOffer]:
        """Обёртка над search() с защитой от исключений.

        Ядро всегда вызывает именно её, чтобы падение одного провайдера не
        ломало проверку остальных.
        """
        if not self.supports_benefit(query.benefit):
            logger.debug(
                "Провайдер %s не поддерживает льготу %s — пропуск",
                self.name,
                query.benefit.value,
            )
            return []
        try:
            return await self.search(query)
        except Exception:  # noqa: BLE001 — намеренно глушим любой сбой провайдера
            logger.exception("Ошибка в провайдере %s при поиске", self.name)
            return []
