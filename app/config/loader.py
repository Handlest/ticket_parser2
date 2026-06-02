"""Загрузка и валидация setup.yaml.

Все настраиваемые параметры приложения живут в одном YAML-файле. Здесь он
читается, в нём подставляются переменные окружения вида ${VAR}, после чего
структура валидируется через pydantic — так при опечатке в конфиге приложение
падает на старте с понятной ошибкой, а не где-то в середине работы.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Шаблон для подстановки переменных окружения: ${VAR_NAME}
_ENV_PATTERN = re.compile(r"\$\{([^}^{]+)\}")


class TelegramConfig(BaseModel):
    token: str
    allowed_user_ids: list[int] = Field(default_factory=list)


class DatabaseConfig(BaseModel):
    path: str = "data/tracking.db"


class SchedulerConfig(BaseModel):
    default_check_interval_minutes: int = 60
    min_interval_minutes: int = 15


class ProvidersConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)
    request_timeout_seconds: int = 30
    headless: bool = True


class LocaleConfig(BaseModel):
    currency: str = "RUB"
    language: str = "ru"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    # Файл со всеми логами (уровня level и выше). Пусто = не писать в файл.
    file: str = "data/logs/app.log"
    # Отдельный файл только для ошибок (ERROR и выше). Пусто = не писать.
    error_file: str = "data/logs/errors.log"
    # Параметры ротации, чтобы файлы не росли бесконечно.
    max_file_size_mb: int = 5
    backup_count: int = 3


class AppConfig(BaseModel):
    telegram: TelegramConfig
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    locale: LocaleConfig = Field(default_factory=LocaleConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _substitute_env(value: str) -> str:
    """Заменяет ${VAR} на значение переменной окружения."""

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            raise ValueError(
                f"Переменная окружения '{var_name}' не задана, "
                f"но используется в setup.yaml. Проверь файл .env."
            )
        return env_value

    return _ENV_PATTERN.sub(replace, value)


def _substitute_recursive(obj: object) -> object:
    """Рекурсивно проходит по структуре конфига и подставляет переменные."""
    if isinstance(obj, dict):
        return {key: _substitute_recursive(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_substitute_recursive(item) for item in obj]
    if isinstance(obj, str):
        return _substitute_env(obj)
    return obj


def load_config(path: str | Path = "setup.yaml") -> AppConfig:
    """Читает и валидирует конфигурацию из YAML-файла."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Файл конфигурации не найден: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    substituted = _substitute_recursive(raw)
    return AppConfig.model_validate(substituted)
