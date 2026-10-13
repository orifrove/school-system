"""Parent/teacher questions with current object-level access checks."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from education.models import Answer, Enrollment, ParentStudent, Question
from education.parent_services import child_profile
from users.models import Role, User
from notifications.services import notify

PAGE_SIZE = 5
TEXT_LIMIT = 500


def _actor(user_id, role):
    user = User.objects.filter(pk=user_id, is_active=True, user_roles__role__code=role).first()
    if user is None:
        raise PermissionDenied("Недостаточно прав.")
    return user


def _enrollments():
    today = timezone.localdate()
    return Enrollment.objects.filter(status=Enrollment.STATUS_ACTIVE, start_date__lte=today).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today))


def _teaching(teacher_id):
    return _enrollments().filter(Q(group__teacher_id=teacher_id, group__is_active=True) |
        Q(group__isnull=True, teacher_id=teacher_id))


def _page(query, page):
    if type(page) is not int or not 0 <= page <= 100000:
        raise ValidationError("Некорректная страница.")
    rows = list(query[page * PAGE_SIZE:(page + 1) * PAGE_SIZE + 1])
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE


def _text(text):
    if not isinstance(text, str):
        raise ValidationError("Отправьте текст.")
    text = text.strip()
    if not 1 <= len(text) <= TEXT_LIMIT or any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise ValidationError(f"Введите от 1 до {TEXT_LIMIT} символов без управляющих знаков.")
    return text


def teachers_for_child(parent_id, student_id, page=0):
    child = child_profile(parent_id, student_id)
    enrollments = _enrollments().filter(student=child)
    ids = set(enrollments.filter(group__is_active=True).values_list("group__teacher_id", flat=True))
    ids.update(enrollments.filter(group__isnull=True).values_list("teacher_id", flat=True))
    rows, more = _page(User.objects.filter(pk__in=ids, is_active=True,
        user_roles__role__code=Role.TEACHER).order_by("full_name", "pk"), page)
    return child, rows, more


def compose_context(parent_id, student_id, teacher_id):
    child = child_profile(parent_id, student_id)
    teacher = _actor(teacher_id, Role.TEACHER)
    if not _teaching(teacher.pk).filter(student=child).exists():
        raise PermissionDenied("Этот преподаватель сейчас не ведёт ребёнка.")
    version = Question.objects.filter(parent_id=parent_id).order_by("-pk").values_list("pk", flat=True).first() or 0
    return child, teacher, version


@transaction.atomic
def ask_question(parent_id, student_id, teacher_id, text, version):
    # Serialize submissions from multiple devices/prompts for the same parent.
    if User.objects.select_for_update().filter(pk=parent_id).first() is None:
        raise PermissionDenied("Аккаунт недоступен.")
    _, teacher, current = compose_context(parent_id, student_id, teacher_id)
    if type(version) is not int or version != current:
        raise ValidationError("Вопрос уже отправлен или форма устарела. Откройте её заново.")
    question = Question.objects.create(parent_id=parent_id, student_id=student_id,
                                       teacher_id=teacher_id, text=_text(text))
    if teacher.telegram_id is not None:
        notify(teacher, "question_asked", f"question:{question.pk}",
               {"student_id": student_id, "question_id": question.pk})
    return question


def _teacher_questions(teacher_id):
    _actor(teacher_id, Role.TEACHER)
    teaching = _teaching(teacher_id).filter(student_id=OuterRef("student_id"))
    links = ParentStudent.objects.filter(parent_id=OuterRef("parent_id"), student_id=OuterRef("student_id"))
    return Question.objects.filter(teacher_id=teacher_id, student__is_active=True,
        parent__is_active=True, parent__user_roles__role__code=Role.PARENT).filter(Exists(teaching), Exists(links))


def questions(user_id, role, student_id=0, page=0):
    if role == "p":
        child_profile(user_id, student_id)
        query = Question.objects.filter(parent_id=user_id, student_id=student_id)
    elif role == "t":
        query = _teacher_questions(user_id)
    else:
        raise PermissionDenied("Недостаточно прав.")
    return _page(query.select_related("student", "teacher", "parent").annotate(
        has_answer=Exists(Answer.objects.filter(question_id=OuterRef("pk"))))
        .order_by("has_answer", "-created_at", "-pk"), page)


def question_detail(user_id, role, question_id):
    if role == "p":
        _actor(user_id, Role.PARENT)
        question = Question.objects.filter(pk=question_id, parent_id=user_id).select_related("student", "teacher").first()
        if question:
            child_profile(user_id, question.student_id)
    elif role == "t":
        question = _teacher_questions(user_id).filter(pk=question_id).select_related("student", "parent", "teacher").first()
    else:
        question = None
    if question is None:
        raise PermissionDenied("Вопрос недоступен.")
    answer = Answer.objects.filter(question=question).first()
    return question, answer


@transaction.atomic
def answer_question(teacher_id, question_id, text):
    question = Question.objects.select_for_update().filter(pk=question_id).first()
    if question is None:
        raise PermissionDenied("Вопрос недоступен.")
    question_detail(teacher_id, "t", question_id)
    if Answer.objects.filter(question=question).exists():
        raise ValidationError("На этот вопрос уже ответили.")
    answer = Answer.objects.create(question=question, answered_by_id=teacher_id, text=_text(text))
    question.answered = True
    question.save(update_fields=["answered"])
    if question.parent.telegram_id is not None:
        notify(question.parent, "question_answered", f"answer:{answer.pk}",
               {"student_id": question.student_id, "question_id": question.pk})
    return answer
