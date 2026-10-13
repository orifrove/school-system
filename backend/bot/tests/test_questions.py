from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase

from bot.handlers import questions


class QuestionHandlersTests(SimpleTestCase):
    def state(self, answer=False):
        return SimpleNamespace(clear=AsyncMock(),
            get_state=AsyncMock(return_value=questions.QuestionInput.answer.state if answer else questions.QuestionInput.question.state),
            get_data=AsyncMock(return_value={"question_id": 7} if answer else {"student_id": 2, "teacher_id": 3, "version": 0}))

    async def test_valid_reply_saves_once_and_clears_state(self):
        state = self.state(answer=True)
        message = SimpleNamespace(text="Reply", answer=AsyncMock())
        with patch.object(questions.services, "answer_question", return_value=SimpleNamespace(question_id=7)) as save:
            await questions.submit(message, SimpleNamespace(pk=3), state)
        save.assert_called_once_with(3, 7, "Reply")
        state.clear.assert_awaited_once()

    async def test_validation_keeps_input_for_correction(self):
        state = self.state()
        message = SimpleNamespace(text="", answer=AsyncMock())
        with patch.object(questions.services, "ask_question", side_effect=ValidationError("Bad input")):
            await questions.submit(message, SimpleNamespace(pk=1), state)
        state.clear.assert_not_awaited()
        self.assertIn("Bad input", message.answer.call_args.args[0])

    async def test_revoked_access_clears_state(self):
        state = self.state()
        with patch.object(questions.services, "ask_question", side_effect=PermissionDenied):
            await questions.submit(SimpleNamespace(text="Hello", answer=AsyncMock()), SimpleNamespace(pk=1), state)
        state.clear.assert_awaited_once()

    async def test_missing_state_context_is_handled(self):
        state = self.state()
        state.get_data.return_value = {}
        with patch.object(questions.services, "ask_question") as save:
            await questions.submit(SimpleNamespace(text="Hello", answer=AsyncMock()), SimpleNamespace(pk=1), state)
        save.assert_not_called()
        state.clear.assert_awaited_once()

    async def test_anonymous_callback_cannot_open_prompt(self):
        query = SimpleNamespace(data="qm:ask:1:2", answer=AsyncMock())
        with patch.object(questions, "render", new=AsyncMock()) as render:
            await questions.callback(query, None, self.state())
        render.assert_not_awaited()
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])

    async def test_prompt_callback_stores_version_and_ids(self):
        state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock(), set_data=AsyncMock())
        context = {"student_id": 2, "teacher_id": 3, "version": 10}
        query = SimpleNamespace(data="qm:ask:2:3", answer=AsyncMock(), message=None)
        with patch.object(questions, "render", new=AsyncMock(return_value=("Prompt", None, context))):
            await questions.callback(query, SimpleNamespace(pk=1), state)
        state.set_data.assert_awaited_once_with(context)
        state.set_state.assert_awaited_once_with(questions.QuestionInput.question)

    async def test_photo_prompts_for_text_without_saving(self):
        message = SimpleNamespace(answer=AsyncMock())
        await questions.text_required(message)
        self.assertIn("текстом", message.answer.call_args.args[0])
