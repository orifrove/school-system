from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from bot.handlers.parent import _button, _navigation, _number, _text
from education import messaging_services as services

router = Router()


class QuestionInput(StatesGroup):
    question = State()
    answer = State()


@sync_to_async
def render(user_id, data):
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "qm":
        raise ValueError
    rows, context = [], None
    action = parts[1]
    if action == "teachers" and len(parts) == 4:
        student_id, page = _number(parts[2]), _number(parts[3], zero=True)
        child, teachers, more = services.teachers_for_child(user_id, student_id, page)
        text = f"<b>{_text(child.full_name, 40)}</b>\nВыберите преподавателя:" if teachers else "Сейчас нет доступных преподавателей. Обратитесь к администратору."
        for teacher in teachers:
            rows.append([_button(teacher.full_name[:50], f"qm:ask:{student_id}:{teacher.pk}")])
        _navigation(rows, f"qm:teachers:{student_id}", page, more)
        rows.append([_button("Мои вопросы", f"qm:list:p:{student_id}:0")])
        rows.append([_button("К ребёнку", f"pg:child:{student_id}")])
    elif action == "ask" and len(parts) == 4:
        student_id, teacher_id = _number(parts[2]), _number(parts[3])
        child, teacher, version = services.compose_context(user_id, student_id, teacher_id)
        text = (f"<b>Вопрос преподавателю {_text(teacher.full_name, 40)}</b>\n"
                f"Ребёнок: {_text(child.full_name, 40)}\n"
                "Введите вопрос (до 500 символов). Отправленный текст будет сохранён для преподавателя.\nОтмена: /cancel.")
        context = {"student_id": student_id, "teacher_id": teacher_id, "version": version}
        rows.append([_button("Отмена", f"qm:list:p:{student_id}:0")])
    elif action == "list" and len(parts) == 5:
        role, student_id, page = parts[2], _number(parts[3], zero=True), _number(parts[4], zero=True)
        records, more = services.questions(user_id, role, student_id, page)
        text = "<b>Вопросы родителей</b>" if role == "t" else "<b>Мои вопросы</b>"
        text += "\nСначала вопросы без ответа."
        if not records:
            text += "\nНа этой странице вопросов нет."
        for record in records:
            label = "✅" if record.has_answer else "⏳"
            rows.append([_button(f"{label} #{record.pk} · {record.student.full_name[:35]}", f"qm:view:{role}:{record.pk}")])
        _navigation(rows, f"qm:list:{role}:{student_id}", page, more)
        rows.append([_button("Обновить", data)])
        if role == "p":
            rows.append([_button("Задать вопрос", f"qm:teachers:{student_id}:0")])
            rows.append([_button("К ребёнку", f"pg:child:{student_id}")])
        else:
            text += "\nГлавное меню: /menu"
    elif action in ("view", "answer") and len(parts) in (4, 5):
        role, question_id = parts[2], _number(parts[3])
        page = _number(parts[4], zero=True) if len(parts) == 5 else 0
        question, answer = services.question_detail(user_id, role, question_id)
        if action == "answer" and answer is None:
            raise ValidationError("Ответ пока не поступил.")
        body = answer.text if action == "answer" else question.text
        date = timezone.localtime(answer.created_at if action == "answer" else question.created_at).strftime("%d.%m.%Y %H:%M")
        # Preserve longer Admin-created records through bounded text pages.
        if page and page * 500 >= len(body):
            raise ValueError
        more = len(body) > (page + 1) * 500
        body = body[page * 500:(page + 1) * 500]
        text = (f"<b>{'Ответ' if action == 'answer' else 'Вопрос'} #{question.pk}</b> · {date} (Ташкент)\n"
                f"Ребёнок: {_text(question.student.full_name, 40)}\n"
                f"Преподаватель: {_text(question.teacher.full_name, 40)}\n\n{escape(body)}")
        _navigation(rows, f"qm:{action}:{role}:{question.pk}", page, more)
        if answer and action == "view":
            rows.append([_button("Прочитать ответ", f"qm:answer:{role}:{question.pk}")])
        elif action == "answer":
            rows.append([_button("К вопросу", f"qm:view:{role}:{question.pk}")])
        elif role == "t":
            rows.append([_button("Ответить", f"qm:reply:{question.pk}")])
        else:
            text += "\n\nОжидает ответа."
        rows.append([_button("Обновить", data)])
        rows.append([_button("К вопросам", f"qm:list:{role}:{question.student_id if role == 'p' else 0}:0")])
    elif action == "reply" and len(parts) == 3:
        question_id = _number(parts[2])
        question, answer = services.question_detail(user_id, "t", question_id)
        if answer:
            raise ValidationError("На этот вопрос уже ответили.")
        text = f"<b>Ответ на вопрос #{question.pk}</b>\nВведите ответ (до 500 символов). Отправленный текст будет сохранён для родителя.\nОтмена: /cancel."
        context = {"question_id": question.pk}
        rows.append([_button("Отмена", f"qm:view:t:{question.pk}")])
    else:
        raise ValueError
    return text, InlineKeyboardMarkup(inline_keyboard=rows), context


@router.message(Command("questions"))
async def inbox(message: Message, db_user, state):
    await state.clear()
    if db_user is None:
        await message.answer("Сначала войдите через /start.")
        return
    try:
        text, keyboard, _ = await render(db_user.pk, "qm:list:t:0:0")
    except PermissionDenied:
        await message.answer("Родителю: /children → ребёнок → Вопросы преподавателю.")
        return
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("qm:"))
async def callback(query: CallbackQuery, db_user, state):
    await state.clear()
    if db_user is None:
        await query.answer("Сначала войдите через /start.", show_alert=True)
        return
    try:
        text, keyboard, context = await render(db_user.pk, query.data)
    except (PermissionDenied, ValidationError, ValueError):
        await query.answer("Действие недоступно. Откройте раздел заново.", show_alert=True)
        return
    if context:
        await state.set_data(context)
        await state.set_state(QuestionInput.answer if "question_id" in context else QuestionInput.question)
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer(text, reply_markup=keyboard)


@router.message(StateFilter(QuestionInput.question, QuestionInput.answer), Command("cancel"))
async def cancel(message: Message, state):
    await state.clear()
    await message.answer("Ввод отменён. Главное меню: /menu")


@router.message(StateFilter(QuestionInput.question, QuestionInput.answer), F.text, ~F.text.startswith("/"))
async def submit(message: Message, db_user, state):
    context = await state.get_data()
    if db_user is None:
        await state.clear()
        await message.answer("Сначала войдите через /start.")
        return
    try:
        if await state.get_state() == QuestionInput.question.state:
            question = await sync_to_async(services.ask_question)(db_user.pk, context["student_id"],
                context["teacher_id"], message.text, context["version"])
            destination = f"qm:view:p:{question.pk}"
            text = "Вопрос сохранён. Преподаватель увидит его в разделе «Вопросы родителей»."
        else:
            answer = await sync_to_async(services.answer_question)(db_user.pk, context["question_id"], message.text)
            destination = f"qm:view:t:{answer.question_id}"
            text = "Ответ сохранён. Он доступен родителю в истории вопросов."
    except ValidationError as exc:
        await message.answer(escape(exc.messages[0]) + "\nДля отмены: /cancel.")
        return
    except (PermissionDenied, KeyError):
        await state.clear()
        await message.answer("Доступ изменился или форма устарела. Откройте /menu.")
        return
    await state.clear()
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_button("Открыть вопрос", destination)]]))


@router.message(StateFilter(QuestionInput.question, QuestionInput.answer), ~F.text)
async def text_required(message: Message):
    await message.answer("Отправьте вопрос или ответ текстом, до 500 символов. Отмена: /cancel.")
