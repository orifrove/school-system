from datetime import timedelta
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from education.tests import test_lesson_admin as fixtures
from education.models import Attendance, Grade, Student, Enrollment, Lesson
from users.models import User


class LessonRecordsAdminTests(TestCase):
    def setUp(self):
        fixtures.LessonAdminTests.setUp(self)
        self.student = Student.objects.create(full_name="Journal student")
        self.enrollment = Enrollment.objects.create(student=self.student, group=self.group, start_date=self.day)
        self.attendance = Attendance.objects.create(lesson=self.lesson, student=self.student, status="present", comment="Attendance note")
        self.grade = Grade.objects.create(lesson=self.lesson, enrollment=self.enrollment,
            given_by_teacher=self.teacher, given_at=self.lesson.starts_at, value="8", max_value="10", comment="Grade note")
        self.url = reverse("admin:education_lesson_change", args=[self.lesson.pk])

    def login_with(self, *permissions):
        user = User.objects.create_user(full_name="Limited staff", is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="education", codename__in=permissions))
        self.client.force_login(user)
        return user

    def test_card_shows_attendance_and_grade_history(self):
        response = self.client.get(self.url)
        for text in ("Journal student", "Attendance note", "Grade note", "8/10", "Все оценки этого занятия", "Все отметки этого занятия"):
            self.assertContains(response, text)

    def test_lesson_view_permission_does_not_expose_records_or_counts(self):
        self.login_with("view_lesson")
        response = self.client.get(self.url)
        self.assertNotContains(response, "Journal student")
        self.assertNotContains(response, "Attendance note")
        self.assertNotContains(response, "Grade note")
        listing = self.client.get(reverse("admin:education_lesson_changelist"))
        self.assertNotIn("attendance_count", listing.context["cl"].list_display)
        self.assertNotIn("grade_count", listing.context["cl"].list_display)

    def test_grade_permission_does_not_expose_attendance(self):
        self.login_with("view_lesson", "view_grade")
        response = self.client.get(self.url)
        self.assertContains(response, "Grade note")
        self.assertNotContains(response, "Attendance note")

    def test_attendance_permission_does_not_expose_grades(self):
        self.login_with("view_lesson", "view_attendance")
        response = self.client.get(self.url)
        self.assertContains(response, "Attendance note")
        self.assertNotContains(response, "Grade note")

    def test_counts_are_not_multiplied_by_join(self):
        Grade.objects.create(lesson=self.lesson, enrollment=self.enrollment,
            given_by_teacher=self.teacher, given_at=self.lesson.starts_at, value="B")
        student = Student.objects.create(full_name="Second")
        Attendance.objects.create(lesson=self.lesson, student=student, status="absent")
        response = self.client.get(reverse("admin:education_lesson_changelist"))
        row = response.context["cl"].queryset.get(pk=self.lesson.pk)
        self.assertEqual((row.attendance_total, row.grade_total), (2, 2))

    def test_unattached_and_other_lesson_grades_are_excluded(self):
        Grade.objects.create(enrollment=self.enrollment, given_by_teacher=self.teacher,
            given_at=self.lesson.starts_at, value="Final", comment="Unattached secret")
        other = Lesson.objects.create(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.lesson.starts_at+timedelta(days=1), ends_at=self.lesson.ends_at+timedelta(days=1))
        Grade.objects.create(lesson=other, enrollment=self.enrollment, given_by_teacher=self.teacher,
            given_at=other.starts_at, value="Other", comment="Other lesson secret")
        response = self.client.get(self.url)
        self.assertNotContains(response, "Unattached secret")
        self.assertNotContains(response, "Other lesson secret")

    def test_html_in_comments_is_escaped(self):
        Grade.objects.filter(pk=self.grade.pk).update(comment="<script>alert(1)</script>")
        response = self.client.get(self.url)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_record_tables_cannot_be_edited_by_post(self):
        data = fixtures.LessonAdminTests.data(self)
        data.update(starts_at_1="18:00:00", ends_at_1="19:00:00",
            attendance_journal="absent", grade_journal="999")
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.attendance.refresh_from_db(); self.grade.refresh_from_db()
        self.assertEqual((self.attendance.status, self.grade.value), ("present", "8"))

    def test_all_records_link_filters_correct_lesson(self):
        for model in ("attendance", "grade"):
            response = self.client.get(reverse(f"admin:education_{model}_changelist"), {"lesson__id__exact":self.lesson.pk})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["cl"].queryset.count(), 1)

    def test_grade_table_is_limited_to_twenty_latest_records(self):
        for index in range(21):
            Grade.objects.create(lesson=self.lesson, enrollment=self.enrollment,
                given_by_teacher=self.teacher, given_at=self.lesson.starts_at+timedelta(minutes=index+1),
                value=str(index), comment=f"History-{index:02d}")
        response = self.client.get(self.url)
        self.assertContains(response, "History-20")
        self.assertNotContains(response, "History-00")
        self.assertNotContains(response, "Grade note")

    def test_empty_journal_has_clear_message(self):
        Attendance.objects.all().delete(); Grade.objects.all().delete()
        response = self.client.get(self.url)
        self.assertContains(response, "Отметок пока нет.")
        self.assertContains(response, "Оценок пока нет.")
