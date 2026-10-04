"""
Точка входа бота. architecture.md, раздел 5: Telegram -> Bot entrypoint
(aiogram dispatcher) -> middleware (идентификация) -> Handler.

Dev-режим — polling (не нужен публичный HTTPS-адрес). Webhook для
production — отдельная настройка в Phase 19 (Deployment), не сейчас.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN
from bot.handlers import common, teacher
from bot.middlewares.auth import AuthMiddleware

logger = logging.getLogger(__name__)


async def run_bot() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан в .env — получите токен у @BotFather "
            "и добавьте его в backend/.env"
        )

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()

    # Student data and invite codes belong only in private chats with the bot.
    dispatcher.message.filter(F.chat.type == "private")
    dispatcher.callback_query.filter(F.message.chat.type == "private")
    dispatcher.message.middleware(AuthMiddleware())
    dispatcher.callback_query.middleware(AuthMiddleware())
    dispatcher.include_router(teacher.router)
    dispatcher.include_router(common.router)

    logger.info("Bot starting (polling mode)...")
    await dispatcher.start_polling(bot)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())
