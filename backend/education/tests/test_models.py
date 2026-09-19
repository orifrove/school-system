from django.db import IntegrityError, transaction
from django.test import TestCase

from education.models import Enrollment, Group, Student, Subject
from users.models import User


class SubjectModelTests(TestCase):
    def test_create_subject(self):
        subject = Subject.objects.create(name="Математика")
        self.assertEqual(str(subject), "Математика")

    def test_subject_name_uniqueness(self):
        Subject.objects.create(name="Математика")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Subject.objects.create(name="Математика")


class StudentModelTests(TestCase):
    def test_create_student_without_user(self):
        """MVP: Student не обязан иметь User (Phase 0, вопрос 1)."""
        student = Student.objects.create(full_name="Иванов Иван")
        self.assertIsNone(student.user)
        self.assertTrue(student.is_active)


class GroupModelTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Математика")
        self.teacher = User.objects.create_user(full_name="Учитель Петров")

    def test_create_group(self):
        group = Group.objects.create(
            subject=self.subject, teacher=self.teacher, name="9А", capacity=15
        )
        self.assertEqual(str(group), "9А")

    def test_change_group_teacher_is_simple_update(self):
        """
        database.md, раздел 5: смена учителя — просто UPDATE, Group
        остаётся тем же объектом (это и был главный аргумент за
        Group как отдельную сущность вместо TeachingAssignment).
        """
        group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="9А")
        new_teacher = User.objects.create_user(full_name="Учитель Сидоров")

        group.teacher = new_teacher
        group.save(update_fields=["teacher"])

        group.refresh_from_db()
        self.assertEqual(group.teacher, new_teacher)
        self.assertEqual(group.pk, group.pk)  # тот же объект, не пересоздан

    def test_cannot_delete_subject_with_group(self):
        """PROTECT — database.md, раздел 6."""
        from django.db.models import ProtectedError

        Group.objects.create(subject=self.subject, teacher=self.teacher, name="9А")
        with self.assertRaises(ProtectedError):
            self.subject.delete()

    def test_cannot_delete_teacher_with_group(self):
        from django.db.models import ProtectedError

        Group.objects.create(subject=self.subject, teacher=self.teacher, name="9А")
        with self.assertRaises(ProtectedError):
            self.teacher.delete()


class EnrollmentModelTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Математика")
        self.teacher = User.objects.create_user(full_name="Учитель Петров")
        self.group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="9А")
        self.student = Student.objects.create(full_name="Иванов Иван")

    def test_group_enrollment(self):
        """Групповое обучение: group заполнен, subject/teacher — нет."""
        enrollment = Enrollment.objects.create(
            student=self.student, group=self.group, start_date="2026-09-01"
        )
        self.assertEqual(enrollment.group, self.group)
        self.assertIsNone(enrollment.subject)
        self.assertIsNone(enrollment.teacher)

    def test_individual_enrollment(self):
        """Индивидуальное обучение: subject+teacher заполнены, group — нет."""
        enrollment = Enrollment.objects.create(
            student=self.student,
            subject=self.subject,
            teacher=self.teacher,
            start_date="2026-09-01",
        )
        self.assertIsNone(enrollment.group)
        self.assertEqual(enrollment.subject, self.subject)
        self.assertEqual(enrollment.teacher, self.teacher)

    def test_cannot_create_enrollment_with_neither_group_nor_individual(self):
        """CHECK constraint: нельзя оставить всё пустым."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Enrollment.objects.create(student=self.student, start_date="2026-09-01")

    def test_cannot_create_enrollment_with_group_and_subject_together(self):
        """CHECK constraint: нельзя group + subject одновременно."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Enrollment.objects.create(
                    student=self.student,
                    group=self.group,
                    subject=self.subject,
                    start_date="2026-09-01",
                )

    def test_cannot_create_enrollment_with_subject_but_no_teacher(self):
        """
        CHECK constraint: индивидуальное обучение требует ОБА поля —
        именно та ошибка, которую мы только что воспроизвели вручную
        через psql (subject_id=1, teacher_id=NULL).
        """
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Enrollment.objects.create(
                    student=self.student, subject=self.subject, start_date="2026-09-01"
                )

    def test_cannot_delete_group_with_enrollment(self):
        """
        PROTECT — исправлено после того, как тест обнаружил конфликт
        с CHECK-constraint (SET_NULL мог обнулить все три поля разом,
        нарушая enrollment_group_xor_individual). Group физически
        нельзя удалить, пока есть Enrollment — только деактивировать
        (is_active=False).
        """
        from django.db.models import ProtectedError

        Enrollment.objects.create(student=self.student, group=self.group, start_date="2026-09-01")

        with self.assertRaises(ProtectedError):
            self.group.delete()

    def test_deleting_student_cascades_to_enrollment(self):
        """CASCADE — Enrollment без Student не имеет смысла."""
        enrollment = Enrollment.objects.create(
            student=self.student, group=self.group, start_date="2026-09-01"
        )
        enrollment_id = enrollment.id

        self.student.delete()

        self.assertFalse(Enrollment.objects.filter(id=enrollment_id).exists())


