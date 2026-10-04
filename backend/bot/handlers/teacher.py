"""Private teacher menu: groups -> lessons -> students -> attendance."""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from education import teacher_services as services

router = Router()
STATUS_LABELS = {"present": "Присутствует", "absent": "Отсутствует", "late": "Опоздал", "excused": "Уважительная причина"}


def _button(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def _navigation(rows, prefix, page, more):
    buttons = []
    if page:
        buttons.append(_button("← Назад", f"{prefix}:{page - 1}"))
    if more:
        buttons.append(_button("Далее →", f"{prefix}:{page + 1}"))
    if buttons:
        rows.append(buttons)


def _number(value, *, zero=False):
    if not value.isascii() or not value.isdecimal() or len(value) > 10:
        raise ValueError
    number = int(value)
    if number < (0 if zero else 1):
        raise ValueError
    return number


@sync_to_async
def render_screen(user_id, data):
    """Parse untrusted callback data before invoking authorized use cases."""
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "tg":
        raise ValueError
    action = parts[1]
    rows = []
    if action == "groups" and len(parts) == 3:
        page = _number(parts[2], zero=True)
        groups, more = services.teacher_groups(user_id, page)
        text = "<b>Мои группы</b>" if groups else "Активных групп на этой странице нет."
        for group in groups:
            rows.append([_button(f"{group.name} · {group.subject.name}", f"tg:lessons:{group.pk}:0")])
        _navigation(rows, "tg:groups", page, more)
    elif action == "lessons" and len(parts) == 4:
        group_id, page = _number(parts[2]), _number(parts[3], zero=True)
        group, lessons, more = services.group_lessons(user_id, group_id, page)
        text = f"<b>{escape(group.name)}</b>\nВыберите занятие (время Ташкента):"
        if not lessons:
            text += "\nЗанятий на этой странице нет."
        for lesson in lessons:
            when = timezone.localtime(lesson.starts_at).strftime("%d.%m.%Y %H:%M")
            label = "проведено" if lesson.status == "held" else "запланировано"
            rows.append([_button(f"{when} · {label}", f"tg:roster:{lesson.pk}:0")])
        _navigation(rows, f"tg:lessons:{group_id}", page, more)
        rows.append([_button("Все группы", "tg:groups:0")])
    elif action == "roster" and len(parts) == 4:
        lesson_id, page = _number(parts[2]), _number(parts[3], zero=True)
        lesson, students, statuses, more = services.lesson_roster(user_id, lesson_id, page)
        when = timezone.localtime(lesson.starts_at).strftime("%d.%m.%Y %H:%M")
        text = f"<b>Посещаемость · {when}</b>\nВыберите ученика:"
        if not students:
            text += "\nНет активных учеников на этой странице."
        for student in students:
            status = STATUS_LABELS.get(statuses.get(student.pk), "Не отмечен")
            rows.append([_button(f"{student.full_name} · {status}", f"tg:student:{lesson_id}:{student.pk}:{page}")])
        _navigation(rows, f"tg:roster:{lesson_id}", page, more)
        rows.append([_button("К занятиям", f"tg:lessons:{lesson.schedule.group_id}:0")])
    elif action == "student" and len(parts) == 5:
        lesson_id, student_id, page = _number(parts[2]), _number(parts[3]), _number(parts[4], zero=True)
        lesson, student = services.attendance_student(user_id, lesson_id, student_id)
        text = f"<b>{escape(student.full_name)}</b>\nВыберите отметку посещаемости:"
        for status, label in STATUS_LABELS.items():
            rows.append([_button(label, f"tg:set:{lesson_id}:{student_id}:{status}:{page}")])
        rows.append([_button("К списку учеников", f"tg:roster:{lesson_id}:{page}")])
    elif action == "set" and len(parts) == 6:
        lesson_id, student_id, page = _number(parts[2]), _number(parts[3]), _number(parts[5], zero=True)
        if page > 100000:
            raise ValueError
        services.record_teacher_attendance(user_id, lesson_id, student_id, parts[4])
        text = "Отметка сохранена. Повторная отметка обновит существующую запись."
        rows.append([_button("К списку учеников", f"tg:roster:{lesson_id}:{page}")])
    else:
        raise ValueError
    return text, InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.message(Command("groups"))
async def my_groups(message: Message, db_user):
    if db_user is None:
        await message.answer("Сначала активируйте приглашение через /start.")
        return
    try:
        text, keyboard = await render_screen(db_user.pk, "tg:groups:0")
    except PermissionDenied as exc:
        await message.answer(escape(str(exc)))
        return
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("tg:"))
async def teacher_callback(query: CallbackQuery, db_user):
    if db_user is None:
        await query.answer("Сначала активируйте приглашение через /start.", show_alert=True)
        return
    try:
        text, keyboard = await render_screen(db_user.pk, query.data)
    except (PermissionDenied, ValidationError, ValueError):
        await query.answer("Действие недоступно. Откройте /groups заново.", show_alert=True)
        return
    await query.answer("Сохранено" if query.data.startswith("tg:set:") else None)
    if isinstance(query.message, Message):
        # A new message avoids Telegram's "message is not modified" on repeat clicks.
        await query.message.answer(text, reply_markup=keyboard)
