"""Teacher bot use cases; authorization is rechecked on every request."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from education import authorization, services
from education.models import Attendance, Enrollment, Grade, Group, Lesson, Student
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


def lesson_progress(user_id, lesson_id):
    """Count eligible learners across all pages, not only the displayed page."""
    lesson = _lesson(_teacher(user_id), lesson_id)
    students = _students(lesson)
    counts = dict(Attendance.objects.filter(lesson=lesson, student__in=students)
                  .values("status").annotate(total=Count("pk")).values_list("status", "total"))
    statuses = {status: counts.get(status, 0) for status, _ in Attendance.STATUS_CHOICES}
    total = students.count()
    marked = sum(statuses.values())
    graded = Grade.objects.filter(lesson=lesson, enrollment__group_id=lesson.schedule.group_id,
                                   enrollment__student__in=students).values("enrollment__student_id").distinct().count()
    return lesson, {"total": total, "marked": marked, "remaining": total - marked,
                    "graded": graded, "statuses": statuses}


def next_unmarked_student(user_id, lesson_id):
    """Recompute the next learner when clicked; old buttons never cache a target."""
    lesson = _lesson(_teacher(user_id), lesson_id)
    students = _students(lesson)
    marked = Attendance.objects.filter(lesson=lesson, status__in=dict(Attendance.STATUS_CHOICES)).values("student_id")
    student = students.exclude(pk__in=marked).first()
    if student is None:
        return None, 0
    preceding = students.filter(Q(full_name__lt=student.full_name) |
                                Q(full_name=student.full_name, pk__lt=student.pk)).count()
    return student, preceding // PAGE_SIZE


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


def _grade_enrollment(lesson, student_id):
    day = timezone.localdate(lesson.starts_at)
    enrollments = list(Enrollment.objects.filter(
        group_id=lesson.schedule.group_id, student_id=student_id,
        student__is_active=True, status=Enrollment.STATUS_ACTIVE, start_date__lte=day,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=day)).select_related("student")[:2])
    if len(enrollments) != 1:
        raise PermissionDenied("Не удалось однозначно определить обучение ученика.")
    return enrollments[0]


def grade_context(user_id, lesson_id, student_id):
    lesson = _lesson(_teacher(user_id), lesson_id)
    enrollment = _grade_enrollment(lesson, student_id)
    grades = list(Grade.objects.filter(enrollment=enrollment, lesson=lesson).order_by("-pk")[:5])
    return lesson, enrollment.student, grades, grades[0].pk if grades else 0


@transaction.atomic
def record_teacher_grade(user_id, lesson_id, student_id, value, expected_latest_id):
    """Add an assessment through add_grade; stale menu buttons cannot duplicate it.

    The lesson lock serializes writes from this bot. A new assessment requires
    opening a fresh menu, whose version is the latest grade ID for this learner.
    Existing grades (including their authors) are never overwritten here.
    """
    user = _teacher(user_id)
    lesson = _lesson(user, lesson_id, lock=True)
    enrollment = _grade_enrollment(lesson, student_id)
    if not isinstance(value, str):
        raise ValidationError("Введите оценку текстом.")
    value = value.strip()
    if not value or len(value) > 16 or any(not char.isprintable() for char in value):
        raise ValidationError("Оценка должна содержать от 1 до 16 символов без переноса строки.")
    latest = Grade.objects.filter(enrollment=enrollment, lesson=lesson).order_by("-pk").values_list("pk", flat=True).first() or 0
    if latest != expected_latest_id:
        raise ValidationError("Оценки уже изменились. Откройте карточку ученика заново.")
    return services.add_grade(enrollment=enrollment, given_by_teacher=user, value=value,
                              lesson=lesson, given_at=timezone.now())
