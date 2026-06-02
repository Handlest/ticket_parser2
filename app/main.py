"""Точка входа: поднимает Telegram-бота и планировщик проверок."""

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot import AccessMiddleware, router
from app.config import LoggingConfig, SearchLogConfig, load_config
from app.core import Tracker
from app.db import AirportRepository, Database, TrackingRepository
from app.notifications import Notifier
from app.providers import CityResolver

logger = logging.getLogger(__name__)


def setup_logging(cfg: LoggingConfig) -> None:
    """Настраивает логи: консоль + (опц.) файл всех логов + файл только ошибок."""
    level = getattr(logging, cfg.level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    max_bytes = cfg.max_file_size_mb * 1024 * 1024

    root = logging.getLogger()
    root.setLevel(level)

    # Консоль (stdout) — видно в `docker compose logs`.
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    def add_file_handler(path: str, handler_level: int) -> None:
        if not path:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        handler.setLevel(handler_level)
        handler.setFormatter(formatter)
        root.addHandler(handler)

    add_file_handler(cfg.file, level)
    add_file_handler(cfg.error_file, logging.ERROR)


def setup_search_logging(cfg: SearchLogConfig, max_bytes: int, backups: int) -> None:
    """Настраивает отдельный логгер поисков ("search").

    При указанном файле пишем туда (своя ротация) и НЕ дублируем в общий
    лог/консоль (propagate=False). Если файл не задан — записи идут в общий лог.
    """
    if not cfg.enabled or not cfg.file:
        return
    search_logger = logging.getLogger("search")
    search_logger.setLevel(logging.INFO)
    Path(cfg.file).parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        cfg.file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    search_logger.addHandler(handler)
    search_logger.propagate = False


async def main() -> None:
    config = load_config()
    setup_logging(config.logging)
    setup_search_logging(
        config.search_log,
        config.logging.max_file_size_mb * 1024 * 1024,
        config.logging.backup_count,
    )
    logger.info("Запуск приложения")

    # БД (миграций нет — таблицы создаются здесь).
    database = Database(config.database.path)
    await database.init_models()
    repository = TrackingRepository(database.session_factory)
    airports = AirportRepository(database.session_factory)

    # Резолвер «город → IATA-код» с кэшем в БД (используется ботом и провайдерами).
    resolver = CityResolver(
        airports,
        config.providers.request_timeout_seconds,
        config.providers.headless,
    )

    # Бот и диспетчер.
    bot = Bot(
        token=config.telegram.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()

    # Внедрение зависимостей в хендлеры (приходят как именованные аргументы).
    dispatcher["repository"] = repository
    dispatcher["config"] = config
    dispatcher["resolver"] = resolver

    dispatcher.update.outer_middleware(
        AccessMiddleware(config.telegram.allowed_user_ids)
    )
    dispatcher.include_router(router)

    # Планировщик проверок.
    notifier = Notifier(bot)
    tracker = Tracker(config, repository, notifier, resolver, config.search_log.enabled)
    tracker.start()

    try:
        await dispatcher.start_polling(bot)
    finally:
        tracker.shutdown()
        await bot.session.close()
        await database.dispose()
        logger.info("Приложение остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
