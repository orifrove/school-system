"""
Business logic layer для education app. django-apps.md, раздел 4:
models - тонкие (только данные + DB-constraints), ВСЯ бизнес-логика -
здесь. Telegram handlers и DRF views вызывают только эти функции,
никогда не работают с ORM моделей напрямую.

Каждая функция ниже реализует правило из database.md, раздел 3
("Business rules, которые НЕ выражаются DB constraints") - то есть
правило, которое физически невозможно проверить через CHECK/UNIQUE,
потому что требует сравнения с другими таблицами или с now().
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from education.models import Attendance, Enrollment, Grade, Group, Lesson, Schedule
from education.notification_events import queue_attendance, queue_grade
from education.lesson_lock import lock_lesson_planning


def update_group(group, **fields):
    """
    database.md, раздел 3.1: нельзя менять Group.subject, если у группы
    уже есть учебная история (Enrollment или Schedule).
    """
    if "subject" in fields and fields["subject"] != group.subject:
        has_history = (
            Enrollment.objects.filter(group=group).exists()
            or Schedule.objects.filter(group=group).exists()
        )
        if has_history:
            raise ValidationError(
                "Нельзя сменить предмет группы с учебной историей - создайте новую Group."
            )

    for field, value in fields.items():
        setattr(group, field, value)
    group.save(update_fields=list(fields.keys()))
    return group


def validate_group_teacher_change(group, new_teacher):
    """Read-only preflight; callers that write must hold the planning lock."""
    moving = Lesson.objects.filter(schedule__group=group, status=Lesson.STATUS_PLANNED)
    previous = []
    for lesson in moving.order_by("starts_at", "pk"):
        previous = [other for other in previous if other.ends_at > lesson.starts_at]
        conflict = previous[0] if previous else None
        if conflict is None:
            conflict = Lesson.objects.filter(teacher=new_teacher,
                starts_at__lt=lesson.ends_at, ends_at__gt=lesson.starts_at
            ).exclude(status=Lesson.STATUS_CANCELLED).exclude(pk__in=moving.values("pk")).order_by("pk").first()
        if conflict:
            local = timezone.localtime(lesson.starts_at, timezone.get_default_timezone())
            raise ValidationError(f"Смена преподавателя создаст пересечение: занятия #{lesson.pk} и #{conflict.pk} "
                f"({local:%d.%m.%Y %H:%M}). Исправьте расписание перед сменой преподавателя.")
        previous.append(lesson)


def change_group_teacher(group, new_teacher):
    """Transfer planned lessons atomically; retain held/cancelled snapshots."""
    with transaction.atomic():
        lock_lesson_planning()
        current = Group.objects.select_for_update().get(pk=group.pk)
        if current.teacher_id == new_teacher.pk:
            group.teacher = new_teacher
            return group
        validate_group_teacher_change(current, new_teacher)
        current.teacher = new_teacher
        current.save(update_fields=["teacher"])
        Lesson.objects.filter(schedule__group=current, status=Lesson.STATUS_PLANNED).update(teacher=new_teacher)
    group.teacher = new_teacher
    return group


@transaction.atomic
def mark_attendance(lesson, student, status, marked_by=None):
    """
    database.md, раздел 3.3: Attendance допустим только если Student
    реально "имеет право" присутствовать на этом Lesson - для группового
    занятия через активный Enrollment в этой Group на дату Lesson,
    для индивидуального - только тот единственный Student из
    Schedule.enrollment.

    Upsert по UNIQUE(lesson, student) - повторная отметка исправляет
    существующую запись, не создаёт вторую строку (database.md, раздел 13).
    """
    schedule = lesson.schedule
    lesson_date = timezone.localdate(lesson.starts_at)

    if schedule.group_id is not None:
        eligible = Enrollment.objects.filter(
            student=student,
            group=schedule.group,
            status=Enrollment.STATUS_ACTIVE,
            start_date__lte=lesson_date,
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=lesson_date)
        ).exists()
        if not eligible:
            raise ValidationError(
                "Этот ученик не зачислен (или уже не активен) в группу этого занятия."
            )
    else:
        if schedule.enrollment.student_id != student.id:
            raise ValidationError("Этот ученик не относится к индивидуальному занятию.")

    if status not in dict(Attendance.STATUS_CHOICES):
        raise ValidationError("Некорректная отметка посещаемости.")
    # Serialize changes even for callers outside the bot's teacher wrapper.
    Lesson.objects.select_for_update().get(pk=lesson.pk)
    previous = Attendance.objects.filter(lesson=lesson, student=student).first()
    if previous is not None and previous.status == status:
        return previous
    attendance, _created = Attendance.objects.update_or_create(
        lesson=lesson,
        student=student,
        defaults={
            "status": status,
            "marked_by": marked_by,
            "marked_at": timezone.now(),
            "updated_at": timezone.now(),
        },
    )
    queue_attendance(attendance)
    return attendance


def create_enrollment(student, start_date, end_date=None, group=None, subject=None, teacher=None, **fields):
    """
    database.md, раздел 3.4: два активных Enrollment одного Student
    в одном обучении (той же Group, либо той же паре subject+teacher
    для individual) не могут пересекаться по датам.

    MVP-стратегия: service layer + tests (не DB exclusion constraint,
    см. database.md для обоснования и путь эскалации в V2).
    """
    overlap_filter = Q(student=student, status=Enrollment.STATUS_ACTIVE)
    if group is not None:
        overlap_filter &= Q(group=group)
    else:
        overlap_filter &= Q(group__isnull=True, subject=subject, teacher=teacher)

    date_overlap = Q(start_date__lte=end_date) if end_date else Q()
    date_overlap &= Q(end_date__isnull=True) | Q(end_date__gte=start_date)

    if Enrollment.objects.filter(overlap_filter).filter(date_overlap).exists():
        raise ValidationError(
            "У этого ученика уже есть пересекающийся по датам активный Enrollment "
            "в этом же обучении."
        )

    return Enrollment.objects.create(
        student=student, start_date=start_date, end_date=end_date,
        group=group, subject=subject, teacher=teacher, **fields,
    )


@transaction.atomic
def add_grade(enrollment, given_by_teacher, value, lesson=None, **fields):
    """
    database.md, раздел 3.5 / 7: если Grade.lesson указан, Lesson и
    Enrollment обязаны относиться к одному обучению. Postgres CHECK
    не может это проверить (не видит другие таблицы) - проверяется
    здесь и покрывается тестами.
    """
    if lesson is not None:
        schedule = lesson.schedule
        same_teaching = (
            schedule.group_id is not None and schedule.group_id == enrollment.group_id
        ) or (
            schedule.enrollment_id is not None and schedule.enrollment_id == enrollment.id
        )
        if not same_teaching:
            raise ValidationError(
                "Lesson относится к другому обучению - нельзя привязать оценку "
                "к занятию из чужой группы/обучения."
            )

    grade = Grade.objects.create(
        enrollment=enrollment, lesson=lesson, given_by_teacher=given_by_teacher,
        value=value, **fields,
    )
    queue_grade(grade)
    return grade
