"""Read-only parent views, scoped to a current ParentStudent relationship."""

from django.core.exceptions import PermissionDenied, ValidationError
from decimal import Decimal

from django.db.models import Exists, OuterRef, Q, Sum, F, Value, DecimalField
from django.db.models.functions import TruncDate, Greatest
from django.utils import timezone

from education.authorization import user_is_parent_of
from education.models import Attendance, Enrollment, Grade, Lesson, Student
from users.models import Role, User
from billing.models import BillingPeriod, Payment

PAGE_SIZE = 5


def _parent(user_id):
    user = User.objects.filter(pk=user_id, is_active=True, user_roles__role__code=Role.PARENT).first()
    if user is None:
        raise PermissionDenied("Доступно только активному родителю.")
    return user


def _child(user_id, student_id):
    parent = _parent(user_id)
    child = Student.objects.filter(pk=student_id, is_active=True).first()
    if child is None or not user_is_parent_of(parent, child):
        raise PermissionDenied("Данные ребёнка недоступны.")
    return child


def _page(queryset, page):
    if type(page) is not int or not 0 <= page <= 100000:
        raise ValidationError("Некорректная страница.")
    rows = list(queryset[page * PAGE_SIZE:(page + 1) * PAGE_SIZE + 1])
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE


def parent_children(user_id, page=0):
    parent = _parent(user_id)
    return _page(Student.objects.filter(parent_links__parent=parent, is_active=True)
                 .order_by("full_name", "pk"), page)


def child_profile(user_id, student_id):
    return _child(user_id, student_id)


def _billing_periods(child):
    money = DecimalField(max_digits=20, decimal_places=2)
    zero = Value(Decimal("0.00"), output_field=money)
    return BillingPeriod.objects.filter(enrollment__student=child).annotate(
        paid=Sum("payments__amount", default=Decimal("0.00"), output_field=money),
    ).annotate(
        outstanding=Greatest(F("amount_due") - F("paid"), zero, output_field=money),
        credit=Greatest(F("paid") - F("amount_due"), zero, output_field=money),
    ).select_related("enrollment__group__subject", "enrollment__subject")


def child_billing(user_id, student_id, page=0):
    child = _child(user_id, student_id)
    periods = _billing_periods(child)
    rows, more = _page(periods.order_by("-period_start", "-pk"), page)
    # Aggregate per-period balances: excess on one period does not pay another.
    totals = periods.aggregate(**{
        f"total_{name}": Sum(field, default=Decimal("0.00"))
        for name, field in (("due", "amount_due"), ("paid", "paid"),
                            ("outstanding", "outstanding"), ("credit", "credit"))
    })
    return child, rows, more, {key.removeprefix("total_"): value for key, value in totals.items()}


def child_payments(user_id, student_id, period_id, page=0):
    child = _child(user_id, student_id)
    period = _billing_periods(child).filter(pk=period_id).first()
    if period is None:
        raise PermissionDenied("Период оплаты недоступен.")
    rows, more = _page(Payment.objects.filter(billing_period=period)
                       .order_by("-paid_at", "-pk"), page)
    return child, period, rows, more


def child_grades(user_id, student_id, page=0):
    child = _child(user_id, student_id)
    rows, more = _page(Grade.objects.filter(enrollment__student=child)
        .select_related("lesson__subject", "enrollment__subject", "enrollment__group__subject")
        .order_by("-given_at", "-pk"), page)
    return child, rows, more


def child_attendance(user_id, student_id, page=0):
    child = _child(user_id, student_id)
    rows, more = _page(Attendance.objects.filter(student=child).select_related("lesson__subject")
                       .order_by("-lesson__starts_at", "-pk"), page)
    return child, rows, more


def child_upcoming_lessons(user_id, student_id, page=0):
    child = _child(user_id, student_id)
    eligible = Enrollment.objects.filter(student=child, status=Enrollment.STATUS_ACTIVE,
        start_date__lte=OuterRef("local_day")).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=OuterRef("local_day"))).filter(
        Q(group_id=OuterRef("schedule__group_id")) |
        Q(pk=OuterRef("schedule__enrollment_id"), group__isnull=True))
    lessons = Lesson.objects.filter(status=Lesson.STATUS_PLANNED, starts_at__gte=timezone.now())
    lessons = lessons.annotate(local_day=TruncDate("starts_at", tzinfo=timezone.get_default_timezone()))
    lessons = lessons.filter(Exists(eligible)).select_related("subject").order_by("starts_at", "pk")
    rows, more = _page(lessons, page)
    return child, rows, more
