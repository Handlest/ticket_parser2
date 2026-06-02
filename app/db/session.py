"""Подключение к SQLite через async SQLAlchemy.

Никаких миграций: init_models() один раз создаёт таблицы по моделям, если их ещё
нет. Если в будущем поменяется схема — достаточно удалить файл .db (он
пересоздастся) или добавить колонку вручную.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Base

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: str) -> None:
        # Гарантируем, что каталог для файла БД существует.
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine: AsyncEngine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def init_models(self) -> None:
        """Создаёт таблицы, если их ещё нет."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Схема БД инициализирована")

    async def dispose(self) -> None:
        await self.engine.dispose()
