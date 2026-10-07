from datetime import date
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone

from billing.models import BillingPeriod, Payment
from bot.handlers.parent import render_parent_screen
from education import parent_services as services
from education.models import Enrollment, Group, ParentStudent, Student, Subject
from users.models import Role, User, UserRole


class ParentBillingTests(TestCase):
    def setUp(self):
        self.parent = User.objects.create_user(full_name="Parent")
        self.teacher = User.objects.create_user(full_name="Teacher")
        self.role = Role.objects.create(code=Role.PARENT)
        UserRole.objects.create(user=self.parent, role=self.role)
        self.child = Student.objects.create(full_name="Child <A&B>")
        self.link = ParentStudent.objects.create(parent=self.parent, student=self.child)
        self.subject = Subject.objects.create(name="Math <A&B>")
        self.group = Group.objects.create(name="Group", subject=self.subject, teacher=self.teacher)
        self.enrollment = Enrollment.objects.create(student=self.child, group=self.group, start_date="2050-01-01")
        self.period = self.make_period(1, "100.00")

    def make_period(self, month, due, enrollment=None):
        return BillingPeriod.objects.create(enrollment=enrollment or self.enrollment,
            period_start=date(2050, month, 1), period_end=date(2050, month, 28), amount_due=due)

    def pay(self, amount, period=None):
        return Payment.objects.create(billing_period=period or self.period, amount=amount,
            paid_at=timezone.now(), registered_by=self.teacher, comment="Internal note")

    def overview(self, page=0):
        return services.child_billing(self.parent.pk, self.child.pk, page)

    def render(self, data):
        return async_to_sync(render_parent_screen)(self.parent.pk, data)

    def test_partial_payments_and_decimal_totals_do_not_duplicate_due(self):
        self.pay("20.10")
        self.pay("30.20")
        _, rows, more, totals = self.overview()
        self.assertEqual(totals, dict(due=Decimal("100.00"), paid=Decimal("50.30"),
                                     outstanding=Decimal("49.70"), credit=Decimal("0.00")))
        self.assertEqual(rows[0].outstanding, Decimal("49.70"))
        self.assertFalse(more)

    def test_overpayment_does_not_hide_another_period_balance(self):
        self.pay("130")
        self.make_period(2, "50")
        totals = self.overview()[3]
        self.assertEqual(totals["outstanding"], Decimal("50"))
        self.assertEqual(totals["credit"], Decimal("30"))
        self.assertEqual(totals["due"], Decimal("150"))

    def test_summary_covers_all_pages_and_period_order_is_stable(self):
        periods = [self.period] + [self.make_period(n, "100") for n in range(2, 8)]
        _, first, more, totals = self.overview()
        _, second, more2, totals2 = self.overview(1)
        self.assertTrue(more)
        self.assertFalse(more2)
        self.assertEqual([x.pk for x in first + second], [x.pk for x in reversed(periods)])
        self.assertEqual(totals, totals2)
        self.assertEqual(totals["due"], Decimal("700"))

    def test_payment_history_paginates_equal_timestamps(self):
        payments = [self.pay("1") for _ in range(7)]
        Payment.objects.update(paid_at=timezone.now())
        first = services.child_payments(self.parent.pk, self.child.pk, self.period.pk)
        second = services.child_payments(self.parent.pk, self.child.pk, self.period.pk, 1)
        self.assertEqual([p.pk for p in first[2] + second[2]], [p.pk for p in reversed(payments)])
        self.assertTrue(first[3])
        self.assertFalse(second[3])

    def test_ended_individual_enrollment_and_fixed_snapshot_remain_visible(self):
        individual = Enrollment.objects.create(student=self.child, subject=self.subject, teacher=self.teacher,
            start_date="2050-01-01", status="ended", price_override="999")
        period = self.make_period(2, "25", individual)
        self.enrollment.price_override = Decimal("888")
        self.enrollment.save()
        self.assertEqual(self.overview()[3]["due"], Decimal("125"))
        text, _ = self.render(f"pg:payments:{self.child.pk}:{period.pk}:0")
        self.assertIn("Math &lt;A&amp;B&gt;", text)

    def test_foreign_period_cannot_be_accessed_with_own_child_id(self):
        other = Student.objects.create(full_name="Other")
        enrollment = Enrollment.objects.create(student=other, group=self.group, start_date="2050-01-01")
        foreign = self.make_period(2, "999", enrollment)
        self.pay("999", foreign)
        self.assertEqual(self.overview()[3]["due"], Decimal("100"))
        for pk in [foreign.pk, 999999]:
            with self.assertRaises(PermissionDenied):
                self.render(f"pg:payments:{self.child.pk}:{pk}:0")
        with self.assertRaises(PermissionDenied):
            self.render(f"pg:billing:{other.pk}:0")

    def assert_denied(self):
        for data in [f"pg:billing:{self.child.pk}:0", f"pg:payments:{self.child.pk}:{self.period.pk}:0"]:
            with self.assertRaises(PermissionDenied):
                self.render(data)

    def test_revoked_link_rejects_existing_buttons(self):
        self.link.delete()
        self.assert_denied()

    def test_role_is_required(self):
        UserRole.objects.filter(user=self.parent).delete()
        self.assert_denied()

    def test_inactive_parent_is_rejected(self):
        self.parent.is_active = False
        self.parent.save()
        self.assert_denied()

    def test_inactive_child_is_rejected(self):
        self.child.is_active = False
        self.child.save()
        self.assert_denied()

    def test_screens_use_payments_instead_of_stale_status_and_do_not_write(self):
        self.pay("100")
        with CaptureQueriesContext(connection) as queries:
            text, keyboard = self.render(f"pg:billing:{self.child.pk}:0")
            history, _ = self.render(keyboard.inline_keyboard[0][0].callback_data)
        self.assertIn("Оплачено", text)
        self.assertIn("&lt;A&amp;B&gt;", text)
        self.assertNotIn("Internal note", history)
        self.assertFalse(any(q["sql"].lstrip().split()[0].upper() in
                             ("INSERT", "UPDATE", "DELETE") for q in queries))
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, "unpaid")

    def test_zero_due_and_empty_history(self):
        self.period.amount_due = 0
        self.period.save()
        text, _ = self.render(f"pg:billing:{self.child.pk}:0")
        self.assertIn("Оплачено", text)
        history, _ = self.render(f"pg:payments:{self.child.pk}:{self.period.pk}:0")
        self.assertIn("Платежей на этой странице нет", history)
        self.period.delete()
        self.assertEqual(self.overview()[3]["outstanding"], Decimal("0"))

    def test_invalid_pages_and_callbacks_are_rejected(self):
        for page in [-1, True, 100001]:
            with self.assertRaises(ValidationError):
                self.overview(page)
        for data in ["pg:billing:1:-1", "pg:payments:1:0:0", "pg:payments:1:1:0:extra"]:
            with self.assertRaises(ValueError):
                self.render(data)

    def test_card_navigation_and_long_names_fit_message_limit(self):
        _, card = self.render(f"pg:child:{self.child.pk}")
        self.assertIn(f"pg:billing:{self.child.pk}:0", [b.callback_data for row in card.inline_keyboard for b in row])
        self.subject.name = "<" * 255
        self.subject.save()
        for month in range(2, 6):
            self.make_period(month, "99999999.99")
        text, keyboard = self.render(f"pg:billing:{self.child.pk}:0")
        self.assertLess(len(text), 4096)
        self.assertNotIn("<<", text)
        for row in keyboard.inline_keyboard:
            for button in row:
                self.assertLessEqual(len(button.callback_data.encode()), 64)
