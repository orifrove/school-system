"""
Общие handlers, доступные без авторизации: /start и ввод invite-кода.
architecture.md, раздел 3.3 — Telegram User Linking flow.
"""

from html import escape

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from asgiref.sync import sync_to_async
from users.services import activate_invite_code

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db_user) -> None:
    if db_user is not None:
        await message.answer(f"С возвращением, {escape(db_user.full_name)}!\nГруппы преподавателя: /groups")
        return

    await message.answer(
        "Здравствуйте! Чтобы начать пользоваться ботом, введите код приглашения, "
        "который вам выдал администратор учебного центра."
    )


@router.message(F.text, ~F.text.startswith("/"))
async def try_use_invite_code(message: Message, db_user) -> None:
    """
    Любое текстовое сообщение от неавторизованного пользователя
    трактуем как попытку ввести invite-код — простейший MVP-flow,
    без отдельной FSM-состояния (это не нужно для одного шага).
    """
    if db_user is not None:
        return  # уже авторизован, это не обработчик команд для него

    if message.from_user is None:
        return
    code_text = (message.text or "").strip()
    result = await _activate_invite_code(code_text, message.from_user.id)

    if result == "ok":
        await message.answer("Код принят! Добро пожаловать.\nГруппы преподавателя: /groups")
    elif result == "not_found":
        await message.answer("Такой код не найден. Проверьте правильность и попробуйте снова.")
    elif result == "expired":
        await message.answer("Этот код истёк. Обратитесь к администратору за новым.")
    elif result == "used":
        await message.answer("Этот код уже был использован.")
    elif result == "inactive":
        await message.answer("Аккаунт отключён. Обратитесь к администратору.")
    elif result == "already_linked":
        await message.answer("Аккаунт уже привязан. Для изменения привязки обратитесь к администратору.")


_activate_invite_code = sync_to_async(activate_invite_code)
