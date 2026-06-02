"""Middleware ограничения доступа.

Если в setup.yaml задан непустой allowed_user_ids — обрабатываются апдейты только
от этих пользователей. Пустой список = доступ всем.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_ids: list[int]) -> None:
        self._allowed = set(allowed_user_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self._allowed:
            user: User | None = data.get("event_from_user")
            if user is None or user.id not in self._allowed:
                return None
        return await handler(event, data)
