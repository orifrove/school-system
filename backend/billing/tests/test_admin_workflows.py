from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import BillingPeriod, Payment
from education.models import Enrollment, Group, Student, Subject
from users.models import User


class BillingAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="billing_admin", password="test", full_name="Admin")
        self.other = User.objects.create_user(full_name="Other")
        self.client.force_login(self.admin)
        subject = Subject.objects.create(name="Math")
        group = Group.objects.create(name="Group", subject=subject, teacher=self.other)
        student = Student.objects.create(full_name="Student")
        self.enrollment = Enrollment.objects.create(student=student, group=group, start_date="2050-01-01")
        self.period = self.make_period(1, "100")

    def make_period(self, month, amount):
        return BillingPeriod.objects.create(enrollment=self.enrollment, period_start=f"2050-{month:02}-01",
            period_end=f"2050-{month:02}-28", amount_due=amount)

    def payment_data(self, **overrides):
        data = dict(billing_period=self.period.pk, amount="25.10", paid_at_0="2026-10-07",
                    paid_at_1="12:00:00", comment="Receipt", registered_by=self.other.pk)
        data.update(overrides)
        return data

    def pay(self, period, amount):
        return Payment.objects.create(billing_period=period, amount=amount, paid_at=timezone.now(), registered_by=self.other)

    def test_payment_author_is_current_admin_even_when_post_is_forged(self):
        response = self.client.post(reverse("admin:billing_payment_add"), self.payment_data())
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get()
        self.assertEqual(payment.registered_by, self.admin)
        self.assertEqual(payment.amount, Decimal("25.10"))

    def test_payment_correction_preserves_original_author(self):
        payment = self.pay(self.period, "10")
        response = self.client.post(reverse("admin:billing_payment_change", args=[payment.pk]),
                                    self.payment_data(registered_by=self.admin.pk))
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.registered_by, self.other)
        self.assertEqual(payment.amount, Decimal("25.10"))

    def test_nonpositive_payments_are_rejected_in_form(self):
        for amount in ["0", "-1"]:
            response = self.client.post(reverse("admin:billing_payment_add"), self.payment_data(amount=amount))
            self.assertEqual(response.status_code, 200)
            self.assertIn("amount", response.context["adminform"].form.errors)
        self.assertEqual(Payment.objects.count(), 0)

    def period_data(self, **overrides):
        data = dict(enrollment=self.enrollment.pk, period_start="2050-02-01", period_end="2050-02-28",
                    amount_due="50", status="paid", **{"payments-TOTAL_FORMS": "0", "payments-INITIAL_FORMS": "0"})
        data.update(overrides)
        return data

    def test_invalid_period_dates_and_amount_are_rejected(self):
        for overrides, field in [({"period_end": "2050-01-01"}, "period_end"), ({"amount_due": "-1"}, "amount_due")]:
            response = self.client.post(reverse("admin:billing_billingperiod_add"), self.period_data(**overrides))
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context["adminform"].form.errors)
        self.assertEqual(BillingPeriod.objects.count(), 1)

    def test_create_period_ignores_submitted_status(self):
        response = self.client.post(reverse("admin:billing_billingperiod_add"), self.period_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BillingPeriod.objects.exclude(pk=self.period.pk).get().status, "unpaid")

    def test_saved_snapshot_cannot_be_changed_by_forged_post(self):
        response = self.client.post(reverse("admin:billing_billingperiod_change", args=[self.period.pk]),
                                    self.period_data(amount_due="999"))
        self.assertEqual(response.status_code, 302)
        self.period.refresh_from_db()
        self.assertEqual(self.period.amount_due, Decimal("100"))
        self.assertEqual(self.period.period_start.isoformat(), "2050-01-01")

    def test_filters_follow_payments_instead_of_stored_status(self):
        partial = self.make_period(2, "100")
        full = self.make_period(3, "100")
        credit = self.make_period(4, "100")
        zero = self.make_period(5, "0")
        self.pay(partial, "20")
        self.pay(partial, "30")
        self.pay(full, "100")
        self.pay(credit, "150")
        BillingPeriod.objects.filter(pk=self.period.pk).update(status="paid")
        for filter_value, expected in [("unpaid", [self.period.pk]), ("partial", [partial.pk]),
                                        ("paid", [full.pk, credit.pk, zero.pk]), ("credit", [credit.pk])]:
            response = self.client.get(reverse("admin:billing_billingperiod_changelist"), {"balance": filter_value})
            self.assertEqual(response.status_code, 200)
            rows = list(response.context["cl"].result_list)
            self.assertCountEqual([p.pk for p in rows], expected)
            if filter_value == "partial":
                self.assertEqual(rows[0].paid, Decimal("50"))
                self.assertEqual(rows[0].outstanding, Decimal("50"))

    def test_payment_history_is_visible_on_period_page(self):
        self.pay(self.period, "25.10")
        response = self.client.get(reverse("admin:billing_billingperiod_change", args=[self.period.pk]))
        self.assertContains(response, "25.10")
        self.assertContains(response, "Частично оплачено")

    def test_payment_form_has_initial_date(self):
        response = self.client.get(reverse("admin:billing_payment_add"))
        self.assertIsNotNone(response.context["adminform"].form.initial.get("paid_at"))

    def test_nonstaff_user_cannot_view_finances(self):
        self.client.force_login(self.other)
        for name in ["billing_billingperiod_changelist", "billing_payment_add"]:
            response = self.client.get(reverse("admin:" + name))
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login/", response.url)
