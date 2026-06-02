"""Нормализованные модели данных для провайдеров.

Ядро и бот работают только с этими структурами и ничего не знают о конкретных
сайтах. Каждый провайдер на входе получает SearchQuery, на выходе отдаёт список
FlightOffer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domain.benefits import BenefitCategory


@dataclass(slots=True)
class SearchQuery:
    """Нормализованный поисковый запрос."""

    origin: str
    destination: str
    departure_date: date
    max_price: float
    benefit: BenefitCategory = BenefitCategory.NONE
    currency: str = "RUB"


@dataclass(slots=True)
class FlightOffer:
    """Нормализованный найденный билет."""

    provider: str
    origin: str
    destination: str
    departure_date: date
    price: float
    currency: str
    url: str
    airline: str | None = None
    details: str | None = None
