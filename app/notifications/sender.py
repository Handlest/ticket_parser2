"""Отправка уведомлений пользователю в Telegram."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Bot

from app.db.models import Tracking
from app.providers.models import FlightOffer

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify_offer(self, tracking: Tracking, offer: FlightOffer) -> None:
        """Шлёт уведомление о найденном билете дешевле порога."""
        text = self._format(tracking, offer)
        try:
            await self._bot.send_message(
                tracking.user_id, text, disable_web_page_preview=False
            )
        except Exception:  # noqa: BLE001 — например, пользователь заблокировал бота
            logger.exception(
                "Не удалось отправить уведомление user_id=%s", tracking.user_id
            )

    @staticmethod
    def _format(tracking: Tracking, offer: FlightOffer) -> str:
        airline = escape(offer.airline or offer.provider)
        lines = [
            "✈️ <b>Найден билет!</b>",
            f"<b>Маршрут:</b> {escape(offer.origin)} → {escape(offer.destination)}",
            f"<b>Дата:</b> {offer.departure_date:%d.%m.%Y}",
            f"<b>Цена:</b> {offer.price:.0f} {escape(offer.currency)} "
            f"(порог {tracking.max_price:.0f} {escape(tracking.currency)})",
            f"<b>Авиакомпания:</b> {airline}",
            f"<b>Льгота:</b> {escape(tracking.benefit_category.label)}",
        ]
        if offer.details:
            lines.append(f"<b>Рейс:</b> {escape(offer.details)}")
        lines.append(f'\n<a href="{escape(offer.url, quote=True)}">Открыть билет</a>')
        return "\n".join(lines)
