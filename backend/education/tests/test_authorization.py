from django.test import TestCase

from education import authorization
from education.models import Enrollment, Group, ParentStudent, Student, Subject
from users.models import User


class AuthorizationTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Математика")
        self.teacher_a = User.objects.create_user(full_name="Учитель A")
        self.teacher_b = User.objects.create_user(full_name="Учитель B")
        self.group_a = Group.objects.create(subject=self.subject, teacher=self.teacher_a, name="Группа A")
        self.group_b = Group.objects.create(subject=self.subject, teacher=self.teacher_b, name="Группа B")

        self.student = Student.objects.create(full_name="Ученик")
        Enrollment.objects.create(student=self.student, group=self.group_a, start_date="2026-09-01")

        self.parent_a = User.objects.create_user(full_name="Родитель A")
        self.parent_b = User.objects.create_user(full_name="Родитель B (чужой)")
        ParentStudent.objects.create(parent=self.parent_a, student=self.student, relation="mother")

    def test_teacher_teaches_own_group(self):
        self.assertTrue(authorization.user_teaches_group(self.teacher_a, self.group_a))

    def test_teacher_does_not_teach_other_group(self):
        self.assertFalse(authorization.user_teaches_group(self.teacher_a, self.group_b))

    def test_parent_is_parent_of_own_child(self):
        self.assertTrue(authorization.user_is_parent_of(self.parent_a, self.student))

    def test_stranger_parent_is_not_parent(self):
        self.assertFalse(authorization.user_is_parent_of(self.parent_b, self.student))

    def test_own_parent_can_view_student(self):
        self.assertTrue(authorization.user_can_view_student(self.parent_a, self.student))

    def test_teacher_of_group_can_view_student(self):
        self.assertTrue(authorization.user_can_view_student(self.teacher_a, self.student))

    def test_teacher_b_cannot_view_student_of_group_a(self):
        """Ключевой security-тест: Teacher B не должен видеть учеников Teacher A."""
        self.assertFalse(authorization.user_can_view_student(self.teacher_b, self.student))

    def test_stranger_parent_cannot_view_student(self):
        """Ключевой security-тест: Parent B не должен видеть чужого ребёнка."""
        self.assertFalse(authorization.user_can_view_student(self.parent_b, self.student))