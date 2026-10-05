"""Parent menu. Callback IDs are untrusted; services check every relationship."""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from education import parent_services as services

router = Router()
STATUS_LABELS = {"present": "Присутствовал", "absent": "Отсутствовал", "late": "Опоздал", "excused": "Уважительная причина"}


def _button(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def _number(value, zero=False):
    if not value.isascii() or not value.isdecimal() or len(value) > 10:
        raise ValueError
    number = int(value)
    if number < (0 if zero else 1):
        raise ValueError
    return number


def _text(value, limit=60):
    # Bound worst-case HTML expansion so a page fits Telegram's message limit.
    return escape(str(value)[:limit])


def _navigation(rows, prefix, page, more):
    buttons = []
    if page:
        buttons.append(_button("← Назад", f"{prefix}:{page - 1}"))
    if more:
        buttons.append(_button("Далее →", f"{prefix}:{page + 1}"))
    if buttons:
        rows.append(buttons)


@sync_to_async
def render_parent_screen(user_id, data):
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "pg":
        raise ValueError
    action = parts[1]
    rows = []
    if action == "children" and len(parts) == 3:
        page = _number(parts[2], zero=True)
        children, more = services.parent_children(user_id, page)
        text = "<b>Мои дети</b>\nВыберите ребёнка:" if children else "На этой странице нет детей. Если ребёнок не добавлен, обратитесь к администратору."
        for child in children:
            rows.append([_button(child.full_name[:60], f"pg:child:{child.pk}")])
        _navigation(rows, "pg:children", page, more)
    elif action == "child" and len(parts) == 3:
        student_id = _number(parts[2])
        child = services.child_profile(user_id, student_id)
        text = f"<b>{_text(child.full_name)}</b>\nЧто хотите посмотреть?"
        rows = [
            [_button("⭐ Оценки", f"pg:grades:{student_id}:0")],
            [_button("📋 Посещаемость", f"pg:attendance:{student_id}:0")],
            [_button("📅 Ближайшие занятия", f"pg:upcoming:{student_id}:0")],
            [_button("Все дети", "pg:children:0")],
        ]
    elif action in ("grades", "attendance", "upcoming") and len(parts) == 4:
        student_id, page = _number(parts[2]), _number(parts[3], zero=True)
        operation = {"grades": services.child_grades, "attendance": services.child_attendance,
                     "upcoming": services.child_upcoming_lessons}[action]
        child, records, more = operation(user_id, student_id, page)
        title = {"grades": "Оценки", "attendance": "Посещаемость", "upcoming": "Ближайшие занятия"}[action]
        text = f"<b>{_text(child.full_name)} · {title}</b>\nВремя Ташкента\n"
        if not records:
            text += "\nЗаписей на этой странице пока нет."
        for record in records:
            if action == "grades":
                subject = (record.lesson.subject if record.lesson_id else
                           record.enrollment.group.subject if record.enrollment.group_id else record.enrollment.subject)
                date = timezone.localtime(record.given_at).strftime("%d.%m.%Y")
                maximum = f" / {_text(record.max_value, 16)}" if record.max_value else ""
                text += f"\n{date} · {_text(subject.name)}\nОценка: <b>{_text(record.value, 16)}{maximum}</b>\n"
            elif action == "attendance":
                date = timezone.localtime(record.lesson.starts_at).strftime("%d.%m.%Y %H:%M")
                text += f"\n{date} · {_text(record.lesson.subject.name)}\n{STATUS_LABELS.get(record.status, 'Неизвестная отметка')}\n"
            else:
                starts = timezone.localtime(record.starts_at).strftime("%d.%m.%Y %H:%M")
                ends = timezone.localtime(record.ends_at).strftime("%d.%m.%Y %H:%M")
                room = f"\nКабинет: {_text(record.room, 32)}" if record.room else ""
                text += f"\n{starts} — {ends}\n{_text(record.subject.name)}{room}\n"
        _navigation(rows, f"pg:{action}:{student_id}", page, more)
        rows.append([_button("Обновить", data)])
        rows.append([_button("К ребёнку", f"pg:child:{student_id}")])
        rows.append([_button("Все дети", "pg:children:0")])
    else:
        raise ValueError
    return text, InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.message(Command("children"))
async def my_children(message: Message, db_user, state=None):
    if state is not None:
        await state.clear()
    if db_user is None:
        await message.answer("Сначала активируйте приглашение через /start.")
        return
    try:
        text, keyboard = await render_parent_screen(db_user.pk, "pg:children:0")
    except PermissionDenied as exc:
        await message.answer(escape(str(exc)))
        return
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("pg:"))
async def parent_callback(query: CallbackQuery, db_user, state=None):
    if state is not None:
        await state.clear()
    if db_user is None:
        await query.answer("Сначала активируйте приглашение через /start.", show_alert=True)
        return
    try:
        text, keyboard = await render_parent_screen(db_user.pk, query.data)
    except (PermissionDenied, ValidationError, ValueError):
        await query.answer("Данные недоступны. Откройте /children заново.", show_alert=True)
        return
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer(text, reply_markup=keyboard)
