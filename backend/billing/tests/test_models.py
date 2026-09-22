from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils.dateparse import parse_datetime

from billing.models import BillingPeriod, Payment
from education.models import Enrollment, Group, Student, Subject
from users.models import User


class BillingPeriodModelTests(TestCase):
    def setUp(self):
        subject = Subject.objects.create(name="Математика")
        teacher = User.objects.create_user(full_name="Учитель Романов")
        group = Group.objects.create(subject=subject, teacher=teacher, name="6А")
        student = Student.objects.create(full_name="Фёдоров Глеб")
        self.enrollment = Enrollment.objects.create(
            student=student, group=group, start_date="2026-09-01"
        )

    def test_create_billing_period(self):
        period = BillingPeriod.objects.create(
            enrollment=self.enrollment,
            period_start="2026-09-01",
            period_end="2026-09-30",
            amount_due=Decimal("500000.00"),
        )
        self.assertEqual(period.status, BillingPeriod.STATUS_UNPAID)

    def test_amount_due_snapshot_not_affected_by_price_override_change(self):
        """
        database.md, раздел 8: amount_due — immutable snapshot.
        Изменение Enrollment.price_override НЕ должно задним числом
        менять уже созданный BillingPeriod.
        """
        period = BillingPeriod.objects.create(
            enrollment=self.enrollment,
            period_start="2026-09-01",
            period_end="2026-09-30",
            amount_due=Decimal("500000.00"),
        )

        self.enrollment.price_override = Decimal("999999.00")
        self.enrollment.save(update_fields=["price_override"])

        period.refresh_from_db()
        self.assertEqual(period.amount_due, Decimal("500000.00"))  # не изменилось

    def test_cannot_create_duplicate_period(self):
        BillingPeriod.objects.create(
            enrollment=self.enrollment,
            period_start="2026-09-01",
            period_end="2026-09-30",
            amount_due=Decimal("500000.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BillingPeriod.objects.create(
                    enrollment=self.enrollment,
                    period_start="2026-09-01",
                    period_end="2026-09-30",
                    amount_due=Decimal("500000.00"),
                )

    def test_cannot_create_period_with_negative_amount(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BillingPeriod.objects.create(
                    enrollment=self.enrollment,
                    period_start="2026-09-01",
                    period_end="2026-09-30",
                    amount_due=Decimal("-100.00"),
                )

    def test_cannot_delete_enrollment_with_billing_period(self):
        from django.db.models import ProtectedError

        BillingPeriod.objects.create(
            enrollment=self.enrollment,
            period_start="2026-09-01",
            period_end="2026-09-30",
            amount_due=Decimal("500000.00"),
        )
        with self.assertRaises(ProtectedError):
            self.enrollment.delete()


class PaymentModelTests(TestCase):
    def setUp(self):
        subject = Subject.objects.create(name="Физика")
        teacher = User.objects.create_user(full_name="Учитель Белов")
        group = Group.objects.create(subject=subject, teacher=teacher, name="7Б")
        student = Student.objects.create(full_name="Кузьмина Вера")
        enrollment = Enrollment.objects.create(student=student, group=group, start_date="2026-09-01")
        self.period = BillingPeriod.objects.create(
            enrollment=enrollment,
            period_start="2026-09-01",
            period_end="2026-09-30",
            amount_due=Decimal("500000.00"),
        )
        self.admin = User.objects.create_user(full_name="Админ Центра")

    def test_full_payment(self):
        payment = Payment.objects.create(
            billing_period=self.period,
            amount=Decimal("500000.00"),
            paid_at=parse_datetime("2026-09-05T10:00:00Z"),
            registered_by=self.admin,
        )
        self.assertEqual(payment.amount, Decimal("500000.00"))

    def test_multiple_partial_payments(self):
        """Несколько платежей на один BillingPeriod — 1:N."""
        Payment.objects.create(
            billing_period=self.period,
            amount=Decimal("200000.00"),
            paid_at=parse_datetime("2026-09-05T10:00:00Z"),
            registered_by=self.admin,
        )
        Payment.objects.create(
            billing_period=self.period,
            amount=Decimal("300000.00"),
            paid_at=parse_datetime("2026-09-20T10:00:00Z"),
            registered_by=self.admin,
        )
        total = sum(p.amount for p in self.period.payments.all())
        self.assertEqual(total, Decimal("500000.00"))

    def test_cannot_create_zero_payment(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payment.objects.create(
                    billing_period=self.period,
                    amount=Decimal("0.00"),
                    paid_at=parse_datetime("2026-09-05T10:00:00Z"),
                    registered_by=self.admin,
                )

    def test_cannot_delete_billing_period_with_payment(self):
        from django.db.models import ProtectedError

        Payment.objects.create(
            billing_period=self.period,
            amount=Decimal("500000.00"),
            paid_at=parse_datetime("2026-09-05T10:00:00Z"),
            registered_by=self.admin,
        )
        with self.assertRaises(ProtectedError):
            self.period.delete()