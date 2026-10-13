"""
Общие handlers, доступные без авторизации: /start и ввод invite-кода.
architecture.md, раздел 3.3 — Telegram User Linking flow.
"""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from asgiref.sync import sync_to_async
from users.services import activate_invite_code
from bot.keyboards.main_menu import main_menu
from users.models import Role, UserRole

router = Router()


@sync_to_async
def help_text(user_id):
    if user_id is None:
        return ("<b>Как начать</b>\nПолучите код приглашения у администратора, "
                "откройте /start и отправьте код в этот личный чат.\n"
                "Если код истёк, попросите новый. Пароль или номер телефона отправлять не нужно.")
    roles = set(UserRole.objects.filter(user_id=user_id, user__is_active=True).values_list("role__code", flat=True))
    lines = ["<b>Помощь</b>", "/menu — главное меню", "/cancel — отменить ввод"]
    if Role.TEACHER in roles:
        lines.append("\n<b>Преподавателю</b>\n/groups — группы и журнал\n"
                     "/schedule — групповые и индивидуальные занятия\n"
                     "/questions — вопросы родителей\n"
                     "Откройте занятие и ученика, чтобы отметить посещаемость или поставить оценку.")
    if Role.PARENT in roles:
        lines.append("\n<b>Родителю</b>\n/children — ваши дети\n"
                     "В карточке ребёнка: оценки, посещаемость, расписание, оплаты и вопросы преподавателю.\n"
                     "Если ребёнка нет в списке, попросите администратора проверить связь с вашим аккаунтом.")
    if not roles.intersection({Role.TEACHER, Role.PARENT}):
        lines.append("\nДля этого аккаунта пока нет разделов преподавателя или родителя. Обратитесь к администратору.")
    lines.append("\nВремя занятий — Ташкент. Чтобы увидеть изменения, нажмите «Обновить» или откройте раздел заново.")
    return "\n".join(lines)


@router.message(Command("help"))
async def cmd_help(message: Message, db_user, state=None):
    if state is not None:
        await state.clear()
    text = await help_text(db_user.pk if db_user else None)
    await message.answer(text + "\n\nНезавершённый ввод отменён.")


@router.callback_query(F.data == "help:main")
async def help_callback(query: CallbackQuery, db_user, state=None):
    if state is not None:
        await state.clear()
    text = await help_text(db_user.pk if db_user else None)
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer(text + "\n\nНезавершённый ввод отменён.")


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, db_user, state=None) -> None:
    if state is not None:
        await state.clear()
    if db_user is not None:
        keyboard = await main_menu(db_user.pk)
        prompt = "Выберите раздел:" if keyboard else "Доступных разделов пока нет. Обратитесь к администратору."
        await message.answer(f"С возвращением, {escape(db_user.full_name)}!\n{prompt}", reply_markup=keyboard)
        return

    await message.answer(
        "Здравствуйте! Чтобы начать пользоваться ботом, введите код приглашения, "
        "который вам выдал администратор учебного центра."
    )


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message):
    await message.answer("Неизвестная команда. Справка: /help. Отменить текущий ввод: /cancel.")


@router.message(F.text, ~F.text.startswith("/"))
async def try_use_invite_code(message: Message, db_user) -> None:
    """
    Любое текстовое сообщение от неавторизованного пользователя
    трактуем как попытку ввести invite-код — простейший MVP-flow,
    без отдельной FSM-состояния (это не нужно для одного шага).
    """
    if db_user is not None:
        await message.answer("Выберите действие в /menu. Как пользоваться ботом: /help.")
        return

    if message.from_user is None:
        return
    code_text = (message.text or "").strip()
    result = await _activate_invite_code(code_text, message.from_user.id)

    if result == "ok":
        await message.answer("Код принят! Добро пожаловать.\nОткройте /menu — там доступны разделы для вашей роли.")
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
