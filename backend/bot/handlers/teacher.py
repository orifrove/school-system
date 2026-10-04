"""Private teacher menu: groups -> lessons -> students -> attendance."""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from education import teacher_services as services

router = Router()
STATUS_LABELS = {"present": "Присутствует", "absent": "Отсутствует", "late": "Опоздал", "excused": "Уважительная причина"}


class GradeInput(StatesGroup):
    value = State()


def _student_back(lesson_id, student_id, page):
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("К карточке ученика", f"tg:student:{lesson_id}:{student_id}:{page}")],
        [_button("К списку учеников", f"tg:roster:{lesson_id}:{page}")],
    ])


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
        text = f"<b>Посещаемость и оценки · {when}</b>\nВыберите ученика:"
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
        _, _, grades, _ = services.grade_context(user_id, lesson_id, student_id)
        grade_text = ", ".join(escape(grade.value) for grade in reversed(grades)) or "пока нет"
        when = timezone.localtime(lesson.starts_at).strftime("%d.%m.%Y %H:%M")
        text = f"<b>{escape(student.full_name)}</b>\nЗанятие: {when}\nПоследние оценки: {grade_text}\n\nОтметьте посещаемость или поставьте оценку:"
        buttons = [_button(label, f"tg:set:{lesson_id}:{student_id}:{status}:{page}") for status, label in STATUS_LABELS.items()]
        rows.extend([buttons[:2], buttons[2:]])
        rows.append([_button("⭐ Поставить оценку", f"tg:grade:{lesson_id}:{student_id}:{page}")])
        rows.append([_button("К списку учеников", f"tg:roster:{lesson_id}:{page}")])
    elif action == "set" and len(parts) == 6:
        lesson_id, student_id, page = _number(parts[2]), _number(parts[3]), _number(parts[5], zero=True)
        if page > 100000:
            raise ValueError
        services.record_teacher_attendance(user_id, lesson_id, student_id, parts[4])
        text = "Отметка сохранена. Повторная отметка обновит существующую запись."
        rows.append([_button("К списку учеников", f"tg:roster:{lesson_id}:{page}")])
        rows.append([_button("⭐ Поставить оценку", f"tg:grade:{lesson_id}:{student_id}:{page}")])
    elif action == "grade" and len(parts) == 5:
        lesson_id, student_id, page = _number(parts[2]), _number(parts[3]), _number(parts[4], zero=True)
        lesson, student, grades, version = services.grade_context(user_id, lesson_id, student_id)
        when = timezone.localtime(lesson.starts_at).strftime("%d.%m.%Y %H:%M")
        text = f"<b>{escape(student.full_name)}</b>\nЗанятие: {when}\nВыберите оценку или введите свою:"
        rows.append([_button(value, f"tg:gs:{lesson_id}:{student_id}:{value}:{page}:{version}") for value in ("2", "3", "4", "5")])
        rows.append([_button("✏️ Своя оценка", f"tg:custom:{lesson_id}:{student_id}:{page}:{version}")])
        rows.append([_button("Назад к ученику", f"tg:student:{lesson_id}:{student_id}:{page}")])
    elif action == "gs" and len(parts) == 7:
        lesson_id, student_id = _number(parts[2]), _number(parts[3])
        value, page, version = parts[4], _number(parts[5], zero=True), _number(parts[6], zero=True)
        if value not in ("2", "3", "4", "5") or page > 100000:
            raise ValueError
        services.record_teacher_grade(user_id, lesson_id, student_id, value, version)
        text = f"Оценка <b>{value}</b> сохранена."
        return text, _student_back(lesson_id, student_id, page)
    elif action == "custom" and len(parts) == 6:
        lesson_id, student_id = _number(parts[2]), _number(parts[3])
        page, version = _number(parts[4], zero=True), _number(parts[5], zero=True)
        _, student, _, current = services.grade_context(user_id, lesson_id, student_id)
        if page > 100000 or version != current:
            raise ValidationError("Оценки уже изменились. Откройте карточку заново.")
        text = f"<b>{escape(student.full_name)}</b>\nВведите оценку (1–16 символов), например 8/10 или A.\nДля отмены нажмите кнопку ниже или /cancel."
        rows.append([_button("Отмена", f"tg:student:{lesson_id}:{student_id}:{page}")])
    else:
        raise ValueError
    return text, InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.message(Command("groups"))
async def my_groups(message: Message, db_user, state: FSMContext = None):
    if state is not None:
        await state.clear()
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
async def teacher_callback(query: CallbackQuery, db_user, state: FSMContext = None):
    if state is not None:
        await state.clear()
    if db_user is None:
        await query.answer("Сначала активируйте приглашение через /start.", show_alert=True)
        return
    try:
        text, keyboard = await render_screen(db_user.pk, query.data)
    except ValidationError as exc:
        await query.answer(exc.messages[0], show_alert=True)
        return
    except (PermissionDenied, ValueError):
        await query.answer("Действие недоступно. Откройте /groups заново.", show_alert=True)
        return
    if query.data.startswith("tg:custom:") and state is not None:
        parts = query.data.split(":")
        await state.set_data(dict(lesson_id=int(parts[2]), student_id=int(parts[3]), page=int(parts[4]), version=int(parts[5])))
        await state.set_state(GradeInput.value)
    await query.answer("Сохранено" if query.data.startswith(("tg:set:", "tg:gs:")) else None)
    if isinstance(query.message, Message):
        # A new message avoids Telegram's "message is not modified" on repeat clicks.
        await query.message.answer(text, reply_markup=keyboard)


@router.message(Command("cancel"))
async def cancel_grade(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ввод отменён. Открыть группы: /groups")


@router.message(GradeInput.value, F.text, ~F.text.startswith("/"))
async def save_custom_grade(message: Message, db_user, state: FSMContext):
    context = await state.get_data()
    if db_user is None or not {"lesson_id", "student_id", "page", "version"} <= context.keys():
        await state.clear()
        await message.answer("Откройте /groups и выберите ученика заново.")
        return
    try:
        grade = await sync_to_async(services.record_teacher_grade)(
            db_user.pk, context["lesson_id"], context["student_id"], message.text, context["version"])
    except ValidationError as exc:
        await message.answer(escape(exc.messages[0]), reply_markup=_student_back(
            context["lesson_id"], context["student_id"], context["page"]))
        return
    except PermissionDenied:
        await state.clear()
        await message.answer("Доступ изменился. Откройте /groups заново.")
        return
    await state.clear()
    await message.answer(f"Оценка <b>{escape(grade.value)}</b> сохранена.", reply_markup=_student_back(
        context["lesson_id"], context["student_id"], context["page"]))


@router.message(GradeInput.value, ~F.text)
async def grade_needs_text(message: Message):
    await message.answer("Отправьте оценку текстом или нажмите /cancel.")
