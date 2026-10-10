"""Read-only diagnosis of the recipient prerequisites for academic events."""
from django.core.management.base import BaseCommand, CommandError

from education.models import Grade, Student
from notifications.models import Notification
from users.models import Role, User


class Command(BaseCommand):
    help = "Explain parent notification setup for one student, without sending or changing data."

    def add_arguments(self, parser):
        parser.add_argument("--student-id", type=int, required=True)

    def handle(self, *args, **options):
        student_id = options["student_id"]
        if student_id <= 0:
            raise CommandError("--student-id must be positive.")
        student = Student.objects.filter(pk=student_id).first()
        if student is None:
            raise CommandError("Student not found.")
        self.stdout.write("READ ONLY: no messages sent, no roles or relationships changed.")
        self.stdout.write(f"student#{student.pk}: {'ACTIVE' if student.is_active else 'STUDENT_INACTIVE'}")
        parents = User.objects.filter(parent_links__student=student).prefetch_related("user_roles__role").order_by("pk")
        linked, eligible = 0, 0
        for parent in parents:
            linked += 1
            reasons = []
            if not student.is_active:
                reasons.append("STUDENT_INACTIVE")
            if not parent.is_active:
                reasons.append("ACCOUNT_INACTIVE")
            if not any(link.role.code == Role.PARENT for link in parent.user_roles.all()):
                reasons.append("PARENT_ROLE_MISSING")
            if parent.telegram_id is None:
                reasons.append("TELEGRAM_NOT_LINKED")
            if not reasons:
                eligible += 1
            self.stdout.write(f"user#{parent.pk}: {', '.join(reasons) if reasons else 'ELIGIBLE'}")
        if not linked:
            self.stdout.write("NO_PARENT_LINKS: connect the intended parent via ParentStudent in Admin.")
        self.stdout.write(f"Linked parents: {linked}; eligible recipients: {eligible}.")
        grades = Grade.objects.filter(enrollment__student=student)
        latest = grades.order_by("-created_at", "-pk").first()
        self.stdout.write(f"Grades: {grades.count()}; latest created (UTC): {latest.created_at.isoformat() if latest else 'none'}")
        count = Notification.objects.filter(channel="telegram", payload__student_id=student.pk,
            event_type__in=["grade_added", "attendance_changed"]).count()
        self.stdout.write(f"Academic notification records for this student (all statuses): {count}.")
        if eligible:
            self.stdout.write("Setup ready for NEW events. Record a new grade through the teacher bot, then preview the queue.")
        else:
            self.stdout.write("Resolve the listed prerequisites before creating a new event.")
        self.stdout.write("Existing grades are not replayed. Direct Admin grade edits do not enqueue notifications.")
