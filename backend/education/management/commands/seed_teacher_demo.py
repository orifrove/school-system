"""Create isolated, repeatable demo data for the teacher attendance menu."""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from education.models import Enrollment, Group, Lesson, Schedule, Student, Subject
from education.services import create_enrollment
from users.models import Role, User


class Command(BaseCommand):
    help = "Create a labelled demo group, two synthetic students and today's lesson (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--teacher-id", required=True, type=int)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo data requires DEBUG=True; production is not supported.")
        # Serializes repeated calls for the same teacher despite names not being unique.
        teacher = User.objects.select_for_update().filter(pk=options["teacher_id"], is_active=True).first()
        if teacher is None or not teacher.user_roles.filter(role__code=Role.TEACHER).exists():
            raise CommandError("Select an active user with the Teacher role.")
        today = timezone.localdate()
        subject, _ = Subject.objects.get_or_create(name="[DEMO] Математика")
        group, _ = Group.objects.get_or_create(
            name=f"[DEMO] Проверка посещаемости #{teacher.pk}",
            defaults={"subject": subject, "teacher": teacher},
        )
        if group.teacher_id != teacher.pk or group.subject_id != subject.pk or not group.is_active:
            raise CommandError("Demo group was changed manually; no existing assignments will be overwritten.")
        for number in (1, 2):
            student, _ = Student.objects.get_or_create(full_name=f"[DEMO #{teacher.pk}] Ученик {number}")
            if not student.is_active:
                raise CommandError("Demo student is inactive; no account state will be overwritten.")
            enrollment = Enrollment.objects.filter(student=student, group=group).first()
            if enrollment is None:
                create_enrollment(student=student, group=group, start_date=today)
            elif (enrollment.status != Enrollment.STATUS_ACTIVE or enrollment.start_date > today
                  or (enrollment.end_date is not None and enrollment.end_date < today)):
                raise CommandError("Demo enrollment was changed manually; no learning history will be overwritten.")
        schedule, _ = Schedule.objects.get_or_create(
            group=group, weekday=today.weekday(), start_time=time(18), end_time=time(19),
            defaults={"valid_from": today},
        )
        if not schedule.is_active or schedule.valid_from > today or (schedule.valid_until and schedule.valid_until < today):
            raise CommandError("Demo schedule is not valid today; review it manually.")
        starts_at = timezone.make_aware(datetime.combine(today, time(18)))
        lesson, _ = Lesson.objects.get_or_create(
            schedule=schedule, starts_at=starts_at,
            defaults={"ends_at": starts_at + timedelta(hours=1), "teacher": teacher, "subject": subject},
        )
        if lesson.teacher_id != teacher.pk or lesson.subject_id != subject.pk or lesson.status == Lesson.STATUS_CANCELLED:
            raise CommandError("Demo lesson was changed manually; no lesson history will be overwritten.")
        self.stdout.write(self.style.SUCCESS(
            f"Ready: demo group #{group.pk}; {today} 18:00 ({settings.TIME_ZONE}); 2 demo students. Open /groups."
        ))
