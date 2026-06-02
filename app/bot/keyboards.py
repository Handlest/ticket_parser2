"""Клавиатуры бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain.benefits import BenefitCategory

BENEFIT_CALLBACK_PREFIX = "benefit"


def benefit_keyboard() -> InlineKeyboardMarkup:
    """Inline-клавиатура выбора категории льготы."""
    rows = [
        [
            InlineKeyboardButton(
                text=benefit.label,
                callback_data=f"{BENEFIT_CALLBACK_PREFIX}:{benefit.value}",
            )
        ]
        for benefit in BenefitCategory
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_keyboard(tracking_id: int) -> InlineKeyboardMarkup:
    """Кнопка удаления конкретного отслеживания."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Удалить", callback_data=f"delete:{tracking_id}"
                )
            ]
        ]
    )
