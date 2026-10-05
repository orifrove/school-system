from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase

from bot.handlers import parent


class ParentHandlerTests(SimpleTestCase):
    async def test_anonymous_parent_callback_is_rejected(self):
        query = SimpleNamespace(answer=AsyncMock(), data="pg:child:1")
        with patch.object(parent, "render_parent_screen", new=AsyncMock()) as render:
            await parent.parent_callback(query, None)
        render.assert_not_awaited()
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])

    async def test_bad_callback_is_acknowledged(self):
        query = SimpleNamespace(answer=AsyncMock(), data="pg:child:invalid")
        await parent.parent_callback(query, SimpleNamespace(pk=1))
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])

    async def test_revoked_access_does_not_send_child_data(self):
        query = SimpleNamespace(answer=AsyncMock(), data="pg:child:1")
        with patch.object(parent, "render_parent_screen", new=AsyncMock(side_effect=PermissionDenied)):
            await parent.parent_callback(query, SimpleNamespace(pk=1))
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])

    async def test_children_command_clears_pending_input(self):
        message = SimpleNamespace(answer=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock())
        with patch.object(parent, "render_parent_screen", new=AsyncMock(return_value=("Children", None))):
            await parent.my_children(message, SimpleNamespace(pk=1), state)
        state.clear.assert_awaited_once()
        message.answer.assert_awaited_once_with("Children", reply_markup=None)
