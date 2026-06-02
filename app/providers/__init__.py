"""Пакет провайдеров.

Импорт модулей провайдеров здесь нужен, чтобы сработали декораторы @register
и провайдеры попали в реестр. Добавил новый провайдер — добавь его импорт сюда.
"""

from app.providers import redwing, s7  # noqa: F401 — регистрация через импорт
from app.providers.base import BaseProvider
from app.providers.models import FlightOffer, SearchQuery
from app.providers.registry import (
    available_providers,
    build_enabled_providers,
    register,
)
from app.providers.s7_locations import (
    CityResolver,
    LocationServiceError,
    ResolveResult,
)

__all__ = [
    "BaseProvider",
    "CityResolver",
    "FlightOffer",
    "LocationServiceError",
    "ResolveResult",
    "SearchQuery",
    "available_providers",
    "build_enabled_providers",
    "register",
]
