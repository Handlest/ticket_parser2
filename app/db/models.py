"""Модели БД (SQLAlchemy 2.0).

Таблицы создаются автоматически на старте через Base.metadata.create_all —
миграции (Alembic) намеренно не используются, чтобы не усложнять проект.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.benefits import BenefitCategory


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tracking(Base):
    """Сохранённое пользователем отслеживание билета."""

    __tablename__ = "trackings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Telegram user_id владельца отслеживания.
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    origin: Mapped[str] = mapped_column(String(64))
    destination: Mapped[str] = mapped_column(String(64))
    departure_date: Mapped[date] = mapped_column(Date)

    # Порог цены: уведомляем, если найден билет дешевле.
    max_price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")

    # Категория льготы (значение BenefitCategory).
    benefit: Mapped[str] = mapped_column(
        String(32), default=BenefitCategory.NONE.value
    )

    # Как часто проверять, минуты.
    check_interval_minutes: Mapped[int] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Время последней проверки (для планировщика).
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Цена последнего отправленного уведомления — чтобы не слать повторно
    # уведомление о той же или более высокой цене.
    last_notified_price: Mapped[float | None] = mapped_column(Float, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    @property
    def benefit_category(self) -> BenefitCategory:
        return BenefitCategory(self.benefit)

    def route_label(self) -> str:
        return f"{self.origin} → {self.destination}"


class Airport(Base):
    """Кэш соответствий «город из ввода пользователя → IATA-код».

    Заполняется по мере того, как встречаются новые города: при первом запросе
    код достаётся из автоподсказки S7 и сохраняется сюда навсегда. Дальше тот же
    город резолвится мгновенно из БД, без обращения к сайту.
    """

    __tablename__ = "airports"

    # Нормализованный ввод пользователя (нижний регистр, без лишних пробелов).
    query: Mapped[str] = mapped_column(String(128), primary_key=True)

    # IATA-код для подстановки в deeplink (для городов — агрегатный, напр. MOW).
    iata: Mapped[str] = mapped_column(String(3))

    # Человекочитаемое название из селектора S7 (напр. «Москва, (все аэропорты)»).
    title: Mapped[str] = mapped_column(String(128))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
