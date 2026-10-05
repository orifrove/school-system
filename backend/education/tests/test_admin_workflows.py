from datetime import timedelta

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from education.forms import GroupAdminForm, ParentStudentAdminForm, ScheduleAdminForm
from education.models import Group, Lesson, ParentStudent, Subject
from education.tests import test_teacher_services as fixtures
from users.models import Role, User, UserRole


class AdminWorkflowTests(TestCase):
    def setUp(self):
        fixtures.TeacherServicesTests.setUp(self)
        self.admin_user = User.objects.create_superuser(full_name="Admin", username="admin", password="testpass")
        self.client.force_login(self.admin_user)
        self.request = RequestFactory().post("/admin/")
        self.request.user = self.admin_user

    def group_data(self, **changes):
        return {"name": "Renamed", "subject": self.subject.pk, "teacher": self.teacher.pk, "is_active": True, **changes}

    def test_group_admin_teacher_change_updates_only_planned_lessons(self):
        held = Lesson.objects.create(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.lesson.starts_at - timedelta(days=1), ends_at=self.lesson.ends_at - timedelta(days=1), status="held")
        form = GroupAdminForm(self.group_data(teacher=self.other.pk), instance=self.group)
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save(commit=False)
        admin.site._registry[Group].save_model(self.request, obj, form, change=True)
        self.lesson.refresh_from_db()
        held.refresh_from_db()
        self.group.refresh_from_db()
        self.assertEqual(self.group.teacher, self.other)
        self.assertEqual(self.group.name, "Renamed")
        self.assertEqual(self.lesson.teacher, self.other)
        self.assertEqual(held.teacher, self.teacher)

    def test_group_subject_with_history_is_form_error(self):
        subject = Subject.objects.create(name="Other subject")
        form = GroupAdminForm(self.group_data(subject=subject.pk), instance=self.group)
        self.assertFalse(form.is_valid())
        self.assertIn("subject", form.errors)

    def test_group_rejects_teacher_without_role(self):
        no_role = User.objects.create_user(full_name="No teacher role")
        form = GroupAdminForm(self.group_data(teacher=no_role.pk), instance=self.group)
        self.assertFalse(form.is_valid())
        self.assertIn("teacher", form.errors)

    def test_parent_link_requires_parent_role(self):
        form = ParentStudentAdminForm({"parent": self.teacher.pk, "student": self.student.pk, "relation": "guardian"})
        self.assertFalse(form.is_valid())
        self.assertIn("parent", form.errors)
        parent_role = Role.objects.create(code=Role.PARENT)
        UserRole.objects.create(user=self.teacher, role=parent_role)
        form = ParentStudentAdminForm({"parent": self.teacher.pk, "student": self.student.pk, "relation": "guardian"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_parent_link_can_be_created_inside_student_card(self):
        parent_role = Role.objects.create(code=Role.PARENT)
        UserRole.objects.create(user=self.other, role=parent_role)
        response = self.client.post(reverse("admin:education_student_change", args=[self.student.pk]), {
            "full_name": self.student.full_name, "is_active": "on", "user": "", "birth_date": "",
            "parent_links-TOTAL_FORMS": "1", "parent_links-INITIAL_FORMS": "0",
            "parent_links-MIN_NUM_FORMS": "0", "parent_links-MAX_NUM_FORMS": "1000",
            "parent_links-0-parent": self.other.pk, "parent_links-0-relation": "guardian",
            "enrollments-TOTAL_FORMS": "0", "enrollments-INITIAL_FORMS": "0",
            "enrollments-MIN_NUM_FORMS": "0", "enrollments-MAX_NUM_FORMS": "0",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ParentStudent.objects.filter(parent=self.other, student=self.student).exists())

    def test_schedule_rejects_invalid_times_dates_and_group_enrollment(self):
        data = {"group": self.group.pk, "weekday": 0, "start_time": "12:00", "end_time": "11:00",
                "valid_from": "2026-10-05", "valid_until": "2026-10-04", "is_active": True}
        form = ScheduleAdminForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("end_time", form.errors)
        self.assertIn("valid_until", form.errors)
        data.update(group="", enrollment=self.enrollment.pk, end_time="13:00", valid_until="")
        form = ScheduleAdminForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("enrollment", form.errors)

    def test_admin_lists_and_student_card_render(self):
        for model in ["student", "group", "schedule", "lesson", "attendance", "grade", "parentstudent"]:
            response = self.client.get(reverse(f"admin:education_{model}_changelist"))
            self.assertEqual(response.status_code, 200, model)
        response = self.client.get(reverse("admin:education_student_change", args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "parent_links-TOTAL_FORMS")
