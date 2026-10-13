from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from bot.handlers.questions import render
from education import messaging_services as services
from education.models import Answer, Enrollment, Group, ParentStudent, Question, Student, Subject
from users.models import Role, User, UserRole
from education.notification_events import prepare_parent_notification
from notifications.models import Notification
from notifications.dispatcher import DeliveryRejected
from unittest.mock import patch


class MessagingFixture:
    def setUp(self):
        self.parent = User.objects.create_user(full_name="Parent")
        self.teacher = User.objects.create_user(full_name="Teacher <A&B>")
        self.other = User.objects.create_user(full_name="Other")
        self.parent_role = Role.objects.create(code=Role.PARENT)
        self.teacher_role = Role.objects.create(code=Role.TEACHER)
        UserRole.objects.create(user=self.parent, role=self.parent_role)
        for user in [self.teacher, self.other]:
            UserRole.objects.create(user=user, role=self.teacher_role)
        self.child = Student.objects.create(full_name="Child <A&B>")
        self.link = ParentStudent.objects.create(parent=self.parent, student=self.child)
        self.subject = Subject.objects.create(name="Math")
        self.group = Group.objects.create(name="Group", teacher=self.teacher, subject=self.subject)
        self.enrollment = Enrollment.objects.create(student=self.child, group=self.group, start_date=timezone.localdate())

    def ask(self, text="Question <A&B>"):
        version = services.compose_context(self.parent.pk, self.child.pk, self.teacher.pk)[2]
        return services.ask_question(self.parent.pk, self.child.pk, self.teacher.pk, text, version)


class MessagingTests(MessagingFixture, TestCase):
    def test_only_current_teachers_offered_once(self):
        Enrollment.objects.create(student=self.child, subject=self.subject, teacher=self.teacher, start_date=timezone.localdate())
        self.assertEqual([t.pk for t in services.teachers_for_child(self.parent.pk, self.child.pk)[1]], [self.teacher.pk])
        with self.assertRaises(PermissionDenied):
            services.compose_context(self.parent.pk, self.child.pk, self.other.pk)

    def test_date_boundaries_pause_and_inactive_group(self):
        today = timezone.localdate()
        self.enrollment.end_date = today
        self.enrollment.save()
        self.assertEqual(len(services.teachers_for_child(self.parent.pk, self.child.pk)[1]), 1)
        for field, value in [("start_date", today + timedelta(days=1)), ("status", "paused"), ("end_date", today - timedelta(days=1))]:
            Enrollment.objects.filter(pk=self.enrollment.pk).update(start_date=today, end_date=None, status="active")
            Enrollment.objects.filter(pk=self.enrollment.pk).update(**{field: value})
            self.assertEqual(services.teachers_for_child(self.parent.pk, self.child.pk)[1], [])
        Enrollment.objects.filter(pk=self.enrollment.pk).update(start_date=today, end_date=None, status="active")
        self.group.is_active = False
        self.group.save()
        self.assertEqual(services.teachers_for_child(self.parent.pk, self.child.pk)[1], [])

    def test_individual_teacher_can_receive_question(self):
        Enrollment.objects.create(student=self.child, subject=self.subject, teacher=self.other, start_date=timezone.localdate())
        version = services.compose_context(self.parent.pk, self.child.pk, self.other.pk)[2]
        question = services.ask_question(self.parent.pk, self.child.pk, self.other.pk, "Hello", version)
        self.assertEqual(services.questions(self.other.pk, "t")[0][0].pk, question.pk)

    def test_question_and_answer_end_to_end(self):
        question = self.ask()
        answer = services.answer_question(self.teacher.pk, question.pk, "Answer <A&B>")
        question.refresh_from_db()
        self.assertTrue(question.answered)
        self.assertEqual(services.question_detail(self.parent.pk, "p", question.pk)[1].pk, answer.pk)
        with self.assertRaises(ValidationError):
            services.answer_question(self.teacher.pk, question.pk, "Replacement")
        self.assertEqual(Answer.objects.get().text, "Answer <A&B>")

    def test_repeated_question_prompt_cannot_create_duplicates(self):
        self.ask()
        with self.assertRaises(ValidationError):
            services.ask_question(self.parent.pk, self.child.pk, self.teacher.pk, "Repeat", 0)
        self.assertEqual(Question.objects.count(), 1)
        self.ask("Fresh prompt")
        self.assertEqual(Question.objects.count(), 2)

    def test_another_parent_of_same_child_cannot_read_private_question(self):
        question = self.ask()
        UserRole.objects.create(user=self.other, role=self.parent_role)
        ParentStudent.objects.create(parent=self.other, student=self.child)
        self.assertEqual(services.questions(self.other.pk, "p", self.child.pk)[0], [])
        with self.assertRaises(PermissionDenied):
            services.question_detail(self.other.pk, "p", question.pk)
        with self.assertRaises(PermissionDenied):
            services.answer_question(self.other.pk, question.pk, "Intrusion")

    def test_revoked_parent_link_denies_reads_and_reply(self):
        question = self.ask()
        self.link.delete()
        for user_id, role in [(self.parent.pk, "p"), (self.teacher.pk, "t")]:
            with self.assertRaises(PermissionDenied):
                services.question_detail(user_id, role, question.pk)
        with self.assertRaises(PermissionDenied):
            services.answer_question(self.teacher.pk, question.pk, "Reply")
        self.assertEqual(Answer.objects.count(), 0)

    def test_teacher_change_revokes_form_and_inbox_without_transferring_question(self):
        question = self.ask()
        self.group.teacher = self.other
        self.group.save()
        self.assertEqual(services.questions(self.teacher.pk, "t")[0], [])
        self.assertEqual(services.questions(self.other.pk, "t")[0], [])
        with self.assertRaises(PermissionDenied):
            services.answer_question(self.teacher.pk, question.pk, "Old teacher")
        self.assertEqual(services.question_detail(self.parent.pk, "p", question.pk)[0].pk, question.pk)

    def test_invalid_text_does_not_create_records(self):
        for text in [" ", "x" * 501, "bad\x00", None]:
            with self.assertRaises(ValidationError):
                self.ask(text)
        question = self.ask()
        with self.assertRaises(ValidationError):
            services.answer_question(self.teacher.pk, question.pk, " ")
        question.refresh_from_db()
        self.assertFalse(question.answered)

    def test_roles_and_active_state_rechecked(self):
        question = self.ask()
        UserRole.objects.filter(user=self.teacher).delete()
        with self.assertRaises(PermissionDenied):
            services.answer_question(self.teacher.pk, question.pk, "No role")
        self.parent.is_active = False
        self.parent.save()
        with self.assertRaises(PermissionDenied):
            services.question_detail(self.parent.pk, "p", question.pk)

    def test_pagination_puts_unanswered_first_uses_answer_record(self):
        records = [self.ask(str(i)) for i in range(7)]
        services.answer_question(self.teacher.pk, records[-1].pk, "Done")
        Question.objects.filter(pk=records[-1].pk).update(answered=False)
        first, more = services.questions(self.teacher.pk, "t")
        second, more2 = services.questions(self.teacher.pk, "t", page=1)
        self.assertTrue(more)
        self.assertFalse(more2)
        self.assertEqual(len({q.pk for q in first + second}), 7)
        self.assertEqual(second[-1].pk, records[-1].pk)
        with self.assertRaises(ValidationError):
            services.questions(self.teacher.pk, "t", page=-1)

    def test_screens_escape_text_and_stay_bounded(self):
        question = self.ask('"' * 500)
        services.answer_question(self.teacher.pk, question.pk, '"' * 500)
        for action in ["view", "answer"]:
            text, keyboard, _ = async_to_sync(render)(self.parent.pk, f"qm:{action}:p:{question.pk}")
            self.assertIn("&quot;", text)
            self.assertIn("&lt;A&amp;B&gt;", text)
            self.assertLess(len(text), 4096)
            self.assertTrue(all(len(b.callback_data.encode()) <= 64 for row in keyboard.inline_keyboard for b in row))

    def test_bad_callbacks_are_rejected(self):
        for data in ["qm:view:p:-1", "qm:ask:1:2:3", "qm:list:x:1:0", "qm:teachers:0:0"]:
            with self.assertRaises((ValueError, PermissionDenied)):
                async_to_sync(render)(self.parent.pk, data)

    def test_long_admin_record_can_be_read_in_full_across_pages(self):
        question = self.ask()
        question.text = "A" * 500 + "END OF QUESTION"
        question.save()
        first, keyboard, _ = async_to_sync(render)(self.parent.pk, f"qm:view:p:{question.pk}")
        next_button = keyboard.inline_keyboard[0][0]
        second, _, _ = async_to_sync(render)(self.parent.pk, next_button.callback_data)
        self.assertNotIn("END OF QUESTION", first)
        self.assertIn("END OF QUESTION", second)

    def test_notifications_target_teacher_and_author_and_recheck_access(self):
        self.teacher.telegram_id = 111
        self.teacher.save()
        self.parent.telegram_id = 222
        self.parent.save()
        question = self.ask()
        notice = Notification.objects.get(event_type="question_asked")
        self.assertEqual(notice.recipient_id, self.teacher.pk)
        self.assertEqual(prepare_parent_notification(notice).chat_id, 111)
        services.answer_question(self.teacher.pk, question.pk, "Answer")
        response = Notification.objects.get(event_type="question_answered")
        self.assertEqual(response.recipient_id, self.parent.pk)
        self.assertEqual(prepare_parent_notification(response).chat_id, 222)
        self.link.delete()
        for item in [notice, response]:
            with self.assertRaises(DeliveryRejected):
                prepare_parent_notification(item)

    def test_outbox_failure_rolls_back_question(self):
        self.teacher.telegram_id = 111
        self.teacher.save()
        with patch("education.messaging_services.notify", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.ask()
        self.assertFalse(Question.objects.exists())

    def test_outbox_failure_rolls_back_answer_and_answered_flag(self):
        self.parent.telegram_id = 222
        self.parent.save()
        question = self.ask()
        with patch("education.messaging_services.notify", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                services.answer_question(self.teacher.pk, question.pk, "Reply")
        question.refresh_from_db()
        self.assertFalse(question.answered)
        self.assertFalse(Answer.objects.exists())


class ConcurrentAnswerTests(MessagingFixture, TransactionTestCase):
    def test_simultaneous_replies_create_one_answer(self):
        question = self.ask()
        barrier = Barrier(2)
        def reply():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    services.answer_question(self.teacher.pk, question.pk, "Answer")
                    return "saved"
                except ValidationError:
                    return "duplicate"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reply) for _ in range(2)]
            self.assertCountEqual([f.result(timeout=20) for f in futures], ["saved", "duplicate"])
        self.assertEqual(Answer.objects.count(), 1)
