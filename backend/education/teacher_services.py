"""Teacher bot use cases; authorization is rechecked on every request."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from education import authorization, services
from education.models import Attendance, Enrollment, Group, Lesson, Student
from users.models import Role, User

PAGE_SIZE = 8


def _teacher(user_id):
    user = User.objects.filter(pk=user_id, is_active=True, user_roles__role__code=Role.TEACHER).first()
    if user is None:
        raise PermissionDenied("Доступно только активному преподавателю.")
    return user


def _page(queryset, page):
    if not isinstance(page, int) or not 0 <= page <= 100000:
        raise ValidationError("Некорректная страница.")
    rows = list(queryset[page * PAGE_SIZE:(page + 1) * PAGE_SIZE + 1])
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE


def _group(user, group_id, lock=False):
    groups = Group.objects
    if lock:
        groups = groups.select_for_update()
    group = groups.filter(pk=group_id, is_active=True).first()
    if group is None or not authorization.user_teaches_group(user, group):
        raise PermissionDenied("Группа недоступна.")
    return group


def _lesson(user, lesson_id, lock=False):
    # Lock the group before the lesson, matching change_group_teacher's order.
    group_id = Lesson.objects.filter(pk=lesson_id).values_list("schedule__group_id", flat=True).first()
    group = _group(user, group_id, lock=lock)
    lessons = Lesson.objects.select_related("schedule", "subject")
    if lock:
        lessons = lessons.select_for_update(of=("self",))
    lesson = lessons.filter(pk=lesson_id, schedule__group=group, teacher=user).first()
    if lesson is None or lesson.status == Lesson.STATUS_CANCELLED:
        raise PermissionDenied("Занятие недоступно или отменено.")
    return lesson


def _students(lesson):
    local_date = timezone.localdate(lesson.starts_at)
    eligible = Enrollment.objects.filter(
        group_id=lesson.schedule.group_id, status=Enrollment.STATUS_ACTIVE,
        start_date__lte=local_date,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=local_date))
    return Student.objects.filter(is_active=True, pk__in=eligible.values("student_id")).order_by("full_name", "pk")


def teacher_groups(user_id, page=0):
    user = _teacher(user_id)
    return _page(Group.objects.filter(teacher=user, is_active=True).select_related("subject").order_by("name", "pk"), page)


def group_lessons(user_id, group_id, page=0):
    user = _teacher(user_id)
    group = _group(user, group_id)
    # Latest first; pagination keeps older held lessons available for corrections.
    rows, more = _page(Lesson.objects.filter(schedule__group=group, teacher=user)
                       .exclude(status=Lesson.STATUS_CANCELLED).order_by("-starts_at", "-pk"), page)
    return group, rows, more


def lesson_roster(user_id, lesson_id, page=0):
    lesson = _lesson(_teacher(user_id), lesson_id)
    students, more = _page(_students(lesson), page)
    statuses = dict(Attendance.objects.filter(lesson=lesson, student__in=students).values_list("student_id", "status"))
    return lesson, students, statuses, more


def attendance_student(user_id, lesson_id, student_id):
    lesson = _lesson(_teacher(user_id), lesson_id)
    student = _students(lesson).filter(pk=student_id).first()
    if student is None:
        raise PermissionDenied("Ученик недоступен для этого занятия.")
    return lesson, student


@transaction.atomic
def record_teacher_attendance(user_id, lesson_id, student_id, status):
    user = _teacher(user_id)
    lesson = _lesson(user, lesson_id, lock=True)
    if status not in dict(Attendance.STATUS_CHOICES):
        raise ValidationError("Некорректная отметка посещаемости.")
    student = _students(lesson).filter(pk=student_id).first()
    if student is None:
        raise PermissionDenied("Ученик недоступен для этого занятия.")
    return services.mark_attendance(lesson, student, status, marked_by=user)
