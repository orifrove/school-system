from io import StringIO

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from education.models import ParentStudent, Student
from notifications.models import Notification
from users.models import Role, User, UserRole


class NotificationDiagnosticsTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(full_name="Private child name")
        self.parent = User.objects.create_user(full_name="Private parent name", telegram_id=987654321)
        self.role = Role.objects.create(code=Role.PARENT)

    def run_check(self):
        output = StringIO()
        call_command("check_parent_notifications", student_id=self.student.pk, stdout=output)
        return output.getvalue()

    def test_missing_links_explained_without_exposing_names_or_telegram_ids(self):
        UserRole.objects.create(user=self.parent, role=self.role)
        output = self.run_check()
        self.assertIn("NO_PARENT_LINKS", output)
        self.assertIn("eligible recipients: 0", output)
        self.assertNotIn(self.student.full_name, output)
        self.assertNotIn(self.parent.full_name, output)
        self.assertNotIn(str(self.parent.telegram_id), output)

    def test_reports_all_missing_prerequisites(self):
        ParentStudent.objects.create(parent=self.parent, student=self.student)
        self.parent.is_active = False
        self.parent.telegram_id = None
        self.parent.save()
        self.student.is_active = False
        self.student.save()
        output = self.run_check()
        for reason in ["STUDENT_INACTIVE", "ACCOUNT_INACTIVE", "PARENT_ROLE_MISSING", "TELEGRAM_NOT_LINKED"]:
            self.assertIn(reason, output)
        self.assertIn("eligible recipients: 0", output)

    def test_eligible_parent_with_multiple_roles_counted_once_without_writes(self):
        ParentStudent.objects.create(parent=self.parent, student=self.student)
        UserRole.objects.create(user=self.parent, role=self.role)
        UserRole.objects.create(user=self.parent, role=Role.objects.create(code=Role.TEACHER))
        with CaptureQueriesContext(connection) as queries:
            output = self.run_check()
        self.assertIn("Linked parents: 1; eligible recipients: 1", output)
        self.assertIn("NEW events", output)
        self.assertFalse(any(q["sql"].lstrip().split()[0].upper() in ("INSERT", "UPDATE", "DELETE") for q in queries))
        self.assertEqual(Notification.objects.count(), 0)

    def test_notification_count_is_scoped_to_student_and_academic_telegram_events(self):
        for number, student_id, channel, event in [(1, self.student.pk, "telegram", "grade_added"),
                (2, self.student.pk + 1, "telegram", "grade_added"),
                (3, self.student.pk, "email", "grade_added"), (4, self.student.pk, "telegram", "other")]:
            Notification.objects.create(recipient=self.parent, event_key=str(number), event_type=event,
                payload={"student_id": student_id}, channel=channel)
        self.assertIn("(all statuses): 1.", self.run_check())

    def test_invalid_or_missing_student_fails_clearly(self):
        for student_id in [-1, 0, self.student.pk + 100]:
            with self.assertRaises(CommandError):
                call_command("check_parent_notifications", student_id=student_id, stdout=StringIO())
