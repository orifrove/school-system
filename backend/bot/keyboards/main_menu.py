from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async

from users.models import Role, UserRole


@sync_to_async
def main_menu(user_id):
    roles = set(UserRole.objects.filter(user_id=user_id, user__is_active=True).values_list("role__code", flat=True))
    rows = []
    if Role.TEACHER in roles:
        rows.append([InlineKeyboardButton(text="📚 Мои группы", callback_data="tg:groups:0")])
    if Role.PARENT in roles:
        rows.append([InlineKeyboardButton(text="👨‍👩‍👧 Мои дети", callback_data="pg:children:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
