"""Academic event creation and delivery-time checks for the generic outbox."""

from django.utils import timezone

from education.models import Attendance, Grade, Student
from notifications.dispatcher import DeliveryRejected, PreparedMessage
from notifications.services import notify
from users.models import Role, User


def _parents(student):
    return User.objects.filter(is_active=True, telegram_id__isnull=False,
        user_roles__role__code=Role.PARENT, parent_links__student=student).distinct()


def queue_grade(grade):
    student = grade.enrollment.student
    if not student.is_active:
        return
    for parent in _parents(student):
        notify(parent, "grade_added", f"grade:{grade.pk}",
               {"student_id": student.pk, "grade_id": grade.pk})


def queue_attendance(attendance):
    if not attendance.student.is_active:
        return
    version = attendance.updated_at.isoformat()
    for parent in _parents(attendance.student):
        notify(parent, "attendance_changed", f"attendance:{attendance.pk}:{version}",
               {"student_id": attendance.student_id, "attendance_id": attendance.pk, "version": version})


def prepare_parent_notification(notification):
    payload = notification.payload
    if not isinstance(payload, dict) or type(payload.get("student_id")) is not int:
        raise DeliveryRejected("invalid_payload")
    student = Student.objects.filter(pk=payload["student_id"], is_active=True).first()
    if student is None:
        raise DeliveryRejected("student_unavailable")
    parent = _parents(student).filter(pk=notification.recipient_id).first()
    if parent is None:
        raise DeliveryRejected("recipient_access_revoked")
    if notification.event_type == "grade_added":
        if type(payload.get("grade_id")) is not int:
            raise DeliveryRejected("invalid_payload")
        grade = Grade.objects.filter(pk=payload["grade_id"], enrollment__student=student).select_related(
            "lesson__subject", "enrollment__subject", "enrollment__group__subject").first()
        if grade is None:
            raise DeliveryRejected("record_unavailable")
        subject = (grade.lesson.subject if grade.lesson_id else
                   grade.enrollment.group.subject if grade.enrollment.group_id else grade.enrollment.subject)
        date = timezone.localtime(grade.given_at).strftime("%d.%m.%Y %H:%M")
        maximum = f" / {grade.max_value}" if grade.max_value else ""
        text = f"Новая оценка\n{student.full_name}\n{subject.name} · {date}\nОценка: {grade.value}{maximum}"
    elif notification.event_type == "attendance_changed":
        if type(payload.get("attendance_id")) is not int:
            raise DeliveryRejected("invalid_payload")
        attendance = Attendance.objects.filter(pk=payload["attendance_id"], student=student).select_related("lesson__subject").first()
        if attendance is None or attendance.updated_at is None:
            raise DeliveryRejected("record_unavailable")
        if attendance.updated_at.isoformat() != payload.get("version"):
            raise DeliveryRejected("superseded")
        labels = {"present": "Присутствовал", "absent": "Отсутствовал", "late": "Опоздал", "excused": "Уважительная причина"}
        if attendance.status not in labels:
            raise DeliveryRejected("invalid_attendance_status")
        date = timezone.localtime(attendance.lesson.starts_at).strftime("%d.%m.%Y %H:%M")
        text = f"Посещаемость\n{student.full_name}\n{attendance.lesson.subject.name} · {date}\n{labels[attendance.status]}"
    else:
        raise DeliveryRejected("unsupported_event")
    return PreparedMessage(parent.telegram_id, text + "\n\nВремя Ташкента. Подробнее: /children")
