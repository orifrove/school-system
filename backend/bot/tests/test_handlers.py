from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher, F
from aiogram.types import Chat, Message, Update, User as TelegramUser
from django.test import SimpleTestCase

from bot.handlers import common, teacher
from bot.middlewares.auth import AuthMiddleware


class HandlerTests(SimpleTestCase):
    async def test_start_escapes_user_name(self):
        message = SimpleNamespace(answer=AsyncMock())
        await common.cmd_start(message, SimpleNamespace(full_name="<b>A & B</b>"))
        self.assertIn("&lt;b&gt;A &amp; B&lt;/b&gt;", message.answer.call_args.args[0])

    async def test_invite_success_response(self):
        message = SimpleNamespace(text=" TEST ", from_user=SimpleNamespace(id=123), answer=AsyncMock())
        with patch.object(common, "_activate_invite_code", new=AsyncMock(return_value="ok")) as activate:
            await common.try_use_invite_code(message, None)
        activate.assert_awaited_once_with("TEST", 123)
        self.assertIn("Код принят", message.answer.call_args.args[0])

    async def test_invite_errors_are_explained(self):
        for status in ["not_found", "expired", "used", "inactive", "already_linked"]:
            message = SimpleNamespace(text="TEST", from_user=SimpleNamespace(id=123), answer=AsyncMock())
            with patch.object(common, "_activate_invite_code", new=AsyncMock(return_value=status)):
                await common.try_use_invite_code(message, None)
            message.answer.assert_awaited_once()

    async def test_anonymous_callback_cannot_write(self):
        query = SimpleNamespace(answer=AsyncMock(), data="tg:set:1:2:present:0")
        with patch.object(teacher, "render_screen", new=AsyncMock()) as render:
            await teacher.teacher_callback(query, None)
        render.assert_not_awaited()
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])

    async def test_bad_callback_is_acknowledged(self):
        query = SimpleNamespace(answer=AsyncMock(), data="tg:set:invalid", message=None)
        await teacher.teacher_callback(query, SimpleNamespace(pk=1))
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])

    async def test_inactive_account_stops_handler(self):
        middleware = AuthMiddleware()
        handler = AsyncMock()
        event = SimpleNamespace(answer=AsyncMock())
        with patch.object(middleware, "_get_user", new=AsyncMock(return_value=SimpleNamespace(is_active=False))):
            await middleware(handler, event, {"event_from_user": SimpleNamespace(id=123)})
        handler.assert_not_awaited()
        event.answer.assert_awaited_once()

    async def test_dispatcher_routes_groups_before_invite_and_rejects_group_chat(self):
        # Exercise real aiogram routing without contacting Telegram.
        dispatcher = Dispatcher()
        dispatcher.message.filter(F.chat.type == "private")
        dispatcher.message.middleware(AuthMiddleware())
        dispatcher.include_router(teacher.router)
        dispatcher.include_router(common.router)
        bot = Bot("123456:TEST_TOKEN_FOR_OFFLINE_TESTS")
        def update(chat_type, text, update_id):
            message = Message(message_id=update_id, date=datetime.now(dt_timezone.utc),
                chat=Chat(id=123, type=chat_type), from_user=TelegramUser(id=123, is_bot=False, first_name="T"), text=text)
            return Update(update_id=update_id, message=message)
        with patch.object(AuthMiddleware, "_get_user", new=AsyncMock(return_value=SimpleNamespace(pk=1, is_active=True))), \
             patch.object(teacher, "render_screen", new=AsyncMock(return_value=("Groups", None))) as render, \
             patch.object(common, "_activate_invite_code", new=AsyncMock()) as activate, \
             patch.object(bot.session, "make_request", new=AsyncMock()) as send:
            await dispatcher.feed_update(bot, update("private", "/groups", 1))
            render.assert_awaited_once_with(1, "tg:groups:0")
            activate.assert_not_awaited()
            send.reset_mock()
            await dispatcher.feed_update(bot, update("group", "/groups", 2))
            send.assert_not_awaited()
        await bot.session.close()
