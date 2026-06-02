"""Реестр провайдеров.

Провайдеры регистрируют себя декоратором @register. Ядро запрашивает включённые
в setup.yaml провайдеры по имени — и не зависит от конкретных реализаций.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import ProvidersConfig
from app.providers.base import BaseProvider

if TYPE_CHECKING:
    from app.providers.s7_locations import CityResolver

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[BaseProvider]] = {}


def register(cls: type[BaseProvider]) -> type[BaseProvider]:
    """Декоратор регистрации класса провайдера по его .name."""
    if not cls.name:
        raise ValueError(f"У провайдера {cls.__name__} не задан атрибут name")
    if cls.name in _REGISTRY:
        raise ValueError(f"Провайдер с именем '{cls.name}' уже зарегистрирован")
    _REGISTRY[cls.name] = cls
    return cls


def available_providers() -> list[str]:
    """Список имён всех зарегистрированных провайдеров."""
    return sorted(_REGISTRY)


def build_enabled_providers(
    config: ProvidersConfig, resolver: "CityResolver | None" = None
) -> list[BaseProvider]:
    """Создаёт экземпляры провайдеров, включённых в конфиге.

    resolver («город → IATA-код») прокидывается в провайдеры, которым он нужен
    (сейчас — только S7); остальные его игнорируют.
    """
    providers: list[BaseProvider] = []
    for name in config.enabled:
        provider_cls = _REGISTRY.get(name)
        if provider_cls is None:
            logger.warning(
                "Провайдер '%s' включён в setup.yaml, но не зарегистрирован. "
                "Доступные: %s",
                name,
                ", ".join(available_providers()) or "(нет)",
            )
            continue
        providers.append(provider_cls(config, resolver))
        logger.info("Провайдер '%s' активирован", name)
    return providers
