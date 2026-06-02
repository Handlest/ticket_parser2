"""Категории льгот для авиабилетов.

В РФ это в основном программа субсидированных перевозок (см. docs/benefits.md).
Льгота — это нормализованный enum, который передаётся провайдеру как часть
запроса. Провайдер сам решает, поддерживает ли он данную категорию.
"""

from __future__ import annotations

from enum import Enum


class BenefitCategory(str, Enum):
    NONE = "none"
    YOUTH = "youth"
    PENSIONER = "pensioner"
    LARGE_FAMILY = "large_family"
    FAR_EAST = "far_east"
    DISABLED = "disabled"

    @property
    def label(self) -> str:
        """Человекочитаемое название (RU) для интерфейса бота и уведомлений."""
        return _LABELS[self]


_LABELS: dict[BenefitCategory, str] = {
    BenefitCategory.NONE: "Без льготы",
    BenefitCategory.YOUTH: "Молодёжь (до 23 лет)",
    BenefitCategory.PENSIONER: "Пенсионеры (м 60+/ж 55+)",
    BenefitCategory.LARGE_FAMILY: "Многодетные семьи",
    BenefitCategory.FAR_EAST: "Жители ДФО",
    BenefitCategory.DISABLED: "Инвалиды и сопровождающие",
}
