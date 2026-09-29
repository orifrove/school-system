"""
architecture.md, раздел 4 (access-flow), шаги 1-4:
Telegram update -> достать telegram_id -> найти User -> проверить
account status. Роли (шаг 5) и object-level permissions (шаг 6) —
НЕ здесь, это отдельная забота handler'ов/services, middleware
отвечает только за "кто пишет боту и активен ли его аккаунт".
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TelegramUser

from asgiref.sync import sync_to_async

from users.models import User


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        telegram_user: TelegramUser | None = data.get("event_from_user")

        db_user = None
        if telegram_user is not None:
            db_user = await self._get_user(telegram_user.id)

        data["db_user"] = db_user
        return await handler(event, data)

    @staticmethod
    @sync_to_async
    def _get_user(telegram_id: int):
        """
        Django ORM синхронный — оборачиваем через sync_to_async, так
        как aiogram работает в asyncio, а Django ORM (без async views)
        - нет. Стандартный паттерн для интеграции Django+asyncio-бота.
        """
        return User.objects.filter(telegram_id=telegram_id, is_active=True).first()