"""
Общие handlers, доступные без авторизации: /start и ввод invite-кода.
architecture.md, раздел 3.3 — Telegram User Linking flow.
"""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone

from users.models import InviteCode

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db_user) -> None:
    if db_user is not None:
        await message.answer(f"С возвращением, {db_user.full_name}!")
        return

    await message.answer(
        "Здравствуйте! Чтобы начать пользоваться ботом, введите код приглашения, "
        "который вам выдал администратор учебного центра."
    )


@router.message()
async def try_use_invite_code(message: Message, db_user) -> None:
    """
    Любое текстовое сообщение от неавторизованного пользователя
    трактуем как попытку ввести invite-код — простейший MVP-flow,
    без отдельной FSM-состояния (это не нужно для одного шага).
    """
    if db_user is not None:
        return  # уже авторизован, это не обработчик команд для него

    code_text = (message.text or "").strip()
    result = await _activate_invite_code(code_text, message.from_user.id)

    if result == "ok":
        await message.answer("Код принят! Добро пожаловать.")
    elif result == "not_found":
        await message.answer("Такой код не найден. Проверьте правильность и попробуйте снова.")
    elif result == "expired":
        await message.answer("Этот код истёк. Обратитесь к администратору за новым.")
    elif result == "used":
        await message.answer("Этот код уже был использован.")


@sync_to_async
def _activate_invite_code(code_text: str, telegram_id: int) -> str:
    try:
        invite = InviteCode.objects.select_related("user").get(code=code_text)
    except InviteCode.DoesNotExist:
        return "not_found"

    if invite.status == InviteCode.STATUS_USED:
        return "used"
    if invite.status == InviteCode.STATUS_INVALIDATED:
        return "not_found"
    if invite.expires_at < timezone.now():
        return "expired"

    invite.user.telegram_id = telegram_id
    invite.user.save(update_fields=["telegram_id"])

    invite.status = InviteCode.STATUS_USED
    invite.used_at = timezone.now()
    invite.save(update_fields=["status", "used_at"])

    return "ok"