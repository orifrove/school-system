from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils.dateparse import parse_datetime

from education.models import (
    Answer,
    Attendance,
    Enrollment,
    Grade,
    Group,
    Lesson,
    Question,
    Schedule,
    Student,
    Subject,
)
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






class ScheduleModelTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Английский")
        self.teacher = User.objects.create_user(full_name="Учитель Смирнов")
        self.group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="10Б")
        self.student = Student.objects.create(full_name="Петров Пётр")
        self.individual_enrollment = Enrollment.objects.create(
            student=self.student, subject=self.subject, teacher=self.teacher, start_date="2026-09-01"
        )

    def test_group_schedule(self):
        schedule = Schedule.objects.create(
            group=self.group, weekday=2, start_time="15:00", end_time="16:30", valid_from="2026-09-01"
        )
        self.assertIsNone(schedule.enrollment)

    def test_individual_schedule(self):
        schedule = Schedule.objects.create(
            enrollment=self.individual_enrollment,
            weekday=3,
            start_time="10:00",
            end_time="11:00",
            valid_from="2026-09-01",
        )
        self.assertIsNone(schedule.group)

    def test_cannot_create_schedule_with_both_or_neither(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Schedule.objects.create(
                    weekday=1, start_time="09:00", end_time="10:00", valid_from="2026-09-01"
                )


class LessonModelTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Физика")
        self.teacher = User.objects.create_user(full_name="Учитель Кузнецов")
        self.group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="11А")
        self.schedule = Schedule.objects.create(
            group=self.group, weekday=4, start_time="14:00", end_time="15:30", valid_from="2026-09-01"
        )

    def test_create_lesson(self):
        lesson = Lesson.objects.create(
            schedule=self.schedule,
            teacher=self.teacher,
            subject=self.subject,
            starts_at=parse_datetime("2026-09-04T14:00:00Z"),
            ends_at=parse_datetime("2026-09-04T15:30:00Z"),
        )
        self.assertEqual(lesson.status, Lesson.STATUS_PLANNED)

    def test_cannot_create_lesson_ending_before_starting(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Lesson.objects.create(
                    schedule=self.schedule,
                    teacher=self.teacher,
                    subject=self.subject,
                    starts_at=parse_datetime("2026-09-04T15:30:00Z"),
                    ends_at=parse_datetime("2026-09-04T14:00:00Z"),
                )

    def test_lesson_keeps_teacher_snapshot_after_group_teacher_changes(self):
        """
        Ключевой сценарий денормализации (database.md, раздел 4):
        Lesson не должен "утечь" на нового учителя задним числом.
        """
        lesson = Lesson.objects.create(
            schedule=self.schedule,
            teacher=self.teacher,
            subject=self.subject,
            starts_at=parse_datetime("2026-09-04T14:00:00Z"),
            ends_at=parse_datetime("2026-09-04T15:30:00Z"),
        )
        new_teacher = User.objects.create_user(full_name="Учитель Новый")
        self.group.teacher = new_teacher
        self.group.save(update_fields=["teacher"])

        lesson.refresh_from_db()
        self.assertEqual(lesson.teacher, self.teacher)  # старый, не новый


class AttendanceModelTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Химия")
        self.teacher = User.objects.create_user(full_name="Учитель Волков")
        self.group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="8В")
        self.schedule = Schedule.objects.create(
            group=self.group, weekday=0, start_time="08:30", end_time="09:15", valid_from="2026-09-01"
        )
        self.lesson = Lesson.objects.create(
            schedule=self.schedule,
            teacher=self.teacher,
            subject=self.subject,
            starts_at=parse_datetime("2026-09-07T08:30:00Z"),
            ends_at=parse_datetime("2026-09-07T09:15:00Z"),
        )
        self.student = Student.objects.create(full_name="Сидорова Анна")

    def test_mark_attendance(self):
        attendance = Attendance.objects.create(
            lesson=self.lesson, student=self.student, status=Attendance.STATUS_PRESENT
        )
        self.assertEqual(str(attendance), f"{self.student} — {self.lesson} — present")

    def test_cannot_mark_attendance_twice_for_same_student_lesson(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=Attendance.STATUS_PRESENT)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attendance.objects.create(
                    lesson=self.lesson, student=self.student, status=Attendance.STATUS_ABSENT
                )

    def test_deleting_lesson_cascades_to_attendance(self):
        attendance = Attendance.objects.create(
            lesson=self.lesson, student=self.student, status=Attendance.STATUS_PRESENT
        )
        attendance_id = attendance.id
        self.lesson.delete()
        self.assertFalse(Attendance.objects.filter(id=attendance_id).exists())


class GradeModelTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Биология")
        self.teacher = User.objects.create_user(full_name="Учитель Орлова")
        self.group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="7Г")
        self.student = Student.objects.create(full_name="Николаев Олег")
        self.enrollment = Enrollment.objects.create(
            student=self.student, group=self.group, start_date="2026-09-01"
        )

    def test_create_grade_without_lesson(self):
        """Итоговая оценка, не привязанная к конкретному занятию."""
        grade = Grade.objects.create(
            enrollment=self.enrollment,
            given_by_teacher=self.teacher,
            value="9",
            max_value="10",
            given_at=parse_datetime("2026-09-30T12:00:00Z"),
        )
        self.assertIsNone(grade.lesson)

    def test_grade_keeps_given_by_teacher_after_group_teacher_changes(self):
        """
        database.md, финальный review, п.1: given_by_teacher —
        исторический snapshot, не зависит от текущего Group.teacher.
        """
        grade = Grade.objects.create(
            enrollment=self.enrollment,
            given_by_teacher=self.teacher,
            value="8",
            given_at=parse_datetime("2026-09-15T12:00:00Z"),
        )
        new_teacher = User.objects.create_user(full_name="Учитель Замена")
        self.group.teacher = new_teacher
        self.group.save(update_fields=["teacher"])

        grade.refresh_from_db()
        self.assertEqual(grade.given_by_teacher, self.teacher)




class QuestionAnswerModelTests(TestCase):
    def setUp(self):
        subject = Subject.objects.create(name="История")
        self.teacher = User.objects.create_user(full_name="Учитель Титова")
        group = Group.objects.create(subject=subject, teacher=self.teacher, name="5А")
        self.student = Student.objects.create(full_name="Морозов Артём")
        self.parent = User.objects.create_user(full_name="Родитель Морозова")

    def test_create_question(self):
        question = Question.objects.create(
            parent=self.parent,
            student=self.student,
            teacher=self.teacher,
            text="Как дела у сына на истории?",
        )
        self.assertFalse(question.answered)

    def test_create_answer(self):
        question = Question.objects.create(
            parent=self.parent, student=self.student, teacher=self.teacher, text="Как успехи?"
        )
        answer = Answer.objects.create(
            question=question, text="Всё хорошо, учится на отлично.", answered_by=self.teacher
        )
        self.assertEqual(question.answer, answer)  # обратная сторона OneToOne

    def test_cannot_create_two_answers_for_same_question(self):
        question = Question.objects.create(
            parent=self.parent, student=self.student, teacher=self.teacher, text="Вопрос"
        )
        Answer.objects.create(question=question, text="Первый ответ", answered_by=self.teacher)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Answer.objects.create(question=question, text="Второй ответ", answered_by=self.teacher)

    def test_deleting_question_cascades_to_answer(self):
        question = Question.objects.create(
            parent=self.parent, student=self.student, teacher=self.teacher, text="Вопрос"
        )
        answer = Answer.objects.create(question=question, text="Ответ", answered_by=self.teacher)
        answer_id = answer.id

        question.delete()

        self.assertFalse(Answer.objects.filter(id=answer_id).exists())