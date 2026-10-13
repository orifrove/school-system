"""Materialize recurring schedules without modifying existing lesson history."""
from datetime import date, datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from education.models import Enrollment, Group, Lesson, Schedule
from users.models import Role


@transaction.atomic
def generate_lessons(start, days=14, *, apply=False, schedule_id=None):
    if type(start) is not date or type(days) is not int or not 1 <= days <= 90:
        raise ValidationError("Use a start date and a range of 1 to 90 days.")
    if schedule_id is not None and (type(schedule_id) is not int or schedule_id <= 0):
        raise ValidationError("Schedule ID must be positive.")
    end = start + timedelta(days=days - 1)
    schedules = Schedule.objects.filter(is_active=True, valid_from__lte=end).order_by("pk")
    if schedule_id is not None:
        if not Schedule.objects.filter(pk=schedule_id).exists():
            raise ValidationError("Schedule not found.")
        schedules = schedules.filter(pk=schedule_id)
    if apply:
        schedules = schedules.select_for_update()
    report = {"created": 0, "would_create": 0, "existing": 0, "skipped": 0, "details": []}
    zone = timezone.get_default_timezone()
    for schedule in schedules:
        if schedule.valid_until and schedule.valid_until < start:
            continue
        if schedule.end_time <= schedule.start_time or not 0 <= schedule.weekday <= 6:
            raise ValidationError(f"Schedule #{schedule.pk}: invalid weekday or time interval.")
        if schedule.valid_until and schedule.valid_until < schedule.valid_from:
            raise ValidationError(f"Schedule #{schedule.pk}: invalid validity dates.")
        enrollment = None
        if schedule.group_id:
            groups = Group.objects.all()
            if apply:
                groups = groups.select_for_update()
            source = groups.get(pk=schedule.group_id)
            enabled = source.is_active
        else:
            enrollments = Enrollment.objects.all()
            if apply:
                enrollments = enrollments.select_for_update()
            enrollment = enrollments.get(pk=schedule.enrollment_id)
            if enrollment.group_id is not None:
                raise ValidationError(f"Schedule #{schedule.pk}: individual schedule references group enrollment.")
            source = enrollment
            enabled = enrollment.status == Enrollment.STATUS_ACTIVE and enrollment.student.is_active
        teacher, subject = source.teacher, source.subject
        enabled = enabled and teacher.is_active and subject.is_active and teacher.user_roles.filter(role__code=Role.TEACHER).exists()
        for offset in range(days):
            day = start + timedelta(days=offset)
            if day.weekday() != schedule.weekday or day < schedule.valid_from or (schedule.valid_until and day > schedule.valid_until):
                continue
            if not enabled or (enrollment and (day < enrollment.start_date or (enrollment.end_date and day > enrollment.end_date))):
                report["skipped"] += 1
                continue
            begins = timezone.make_aware(datetime.combine(day, schedule.start_time), zone)
            ends = timezone.make_aware(datetime.combine(day, schedule.end_time), zone)
            if Lesson.objects.filter(schedule=schedule, starts_at=begins).exists():
                report["existing"] += 1
                continue
            if apply:
                _, created = Lesson.objects.get_or_create(schedule=schedule, starts_at=begins,
                    defaults={"ends_at": ends, "teacher": teacher, "subject": subject, "room": schedule.room})
                report["created" if created else "existing"] += 1
            else:
                report["would_create"] += 1
            if len(report["details"]) < 50:
                report["details"].append(f"schedule#{schedule.pk} {day} {schedule.start_time} - {schedule.end_time}")
    return report
