"""Репозиторий для работы с отслеживаниями.

Инкапсулирует все запросы к БД — ядро и бот не пишут SQL напрямую.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Airport, Tracking
from app.domain.benefits import BenefitCategory


class TrackingRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(
        self,
        *,
        user_id: int,
        origin: str,
        destination: str,
        departure_date: date,
        max_price: float,
        benefit: BenefitCategory,
        check_interval_minutes: int,
        currency: str = "RUB",
    ) -> Tracking:
        tracking = Tracking(
            user_id=user_id,
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            max_price=max_price,
            benefit=benefit.value,
            check_interval_minutes=check_interval_minutes,
            currency=currency,
        )
        async with self._session_factory() as session:
            session.add(tracking)
            await session.commit()
            await session.refresh(tracking)
        return tracking

    async def list_by_user(self, user_id: int) -> list[Tracking]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(Tracking)
                .where(Tracking.user_id == user_id, Tracking.is_active.is_(True))
                .order_by(Tracking.departure_date)
            )
            return list(result)

    async def list_active(self) -> list[Tracking]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(Tracking).where(Tracking.is_active.is_(True))
            )
            return list(result)

    async def get(self, tracking_id: int, user_id: int) -> Tracking | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(Tracking).where(
                    Tracking.id == tracking_id, Tracking.user_id == user_id
                )
            )

    async def delete(self, tracking_id: int, user_id: int) -> bool:
        """Удаляет отслеживание пользователя. Возвращает True, если что-то удалено."""
        async with self._session_factory() as session:
            result = await session.execute(
                delete(Tracking).where(
                    Tracking.id == tracking_id, Tracking.user_id == user_id
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def delete_expired(self, today: date) -> int:
        """Удаляет отслеживания с прошедшей датой вылета. Возвращает их число."""
        async with self._session_factory() as session:
            result = await session.execute(
                delete(Tracking).where(Tracking.departure_date < today)
            )
            await session.commit()
            return result.rowcount

    async def mark_checked(
        self, tracking_id: int, notified_price: float | None = None
    ) -> None:
        """Обновляет время проверки и (опционально) цену последнего уведомления."""
        values: dict = {"last_checked_at": datetime.now(timezone.utc)}
        if notified_price is not None:
            values["last_notified_price"] = notified_price
        async with self._session_factory() as session:
            await session.execute(
                update(Tracking).where(Tracking.id == tracking_id).values(**values)
            )
            await session.commit()


class AirportRepository:
    """Кэш соответствий «город → IATA-код» (таблица airports).

    Города кэшируются навсегда: IATA-коды стабильны, поэтому TTL не нужен.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, query: str) -> Airport | None:
        async with self._session_factory() as session:
            return await session.get(Airport, query)

    async def save(self, query: str, iata: str, title: str) -> Airport:
        airport = Airport(query=query, iata=iata, title=title)
        async with self._session_factory() as session:
            await session.merge(airport)
            await session.commit()
        return airport
