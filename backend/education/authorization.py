"""
Object-level authorization checks. architecture.md, раздел 4: роль
(Teacher/Parent/Admin) сама по себе НЕ даёт доступ к данным — только
в сочетании с конкретной связью (Teacher назначен на эту Group,
Parent привязан к этому Student). Эти функции - единственное место,
где такие проверки происходят; Telegram handlers/DRF views вызывают
только их, никогда не проверяют доступ сами.
"""

from education.models import Enrollment, Group, ParentStudent, Student


def user_teaches_group(user, group: Group) -> bool:
    """Teacher назначен на эту конкретную Group прямо сейчас."""
    return group.teacher_id == user.id


def user_teaches_enrollment(user, enrollment: Enrollment) -> bool:
    """
    Teacher ведёт это обучение - либо через текущего Group.teacher
    (групповое), либо напрямую как Enrollment.teacher (индивидуальное).
    """
    if enrollment.group_id is not None:
        return enrollment.group.teacher_id == user.id
    return enrollment.teacher_id == user.id


def user_is_parent_of(user, student: Student) -> bool:
    """Parent привязан к этому конкретному Student через ParentStudent."""
    return ParentStudent.objects.filter(parent=user, student=student).exists()


def user_can_view_student(user, student: Student) -> bool:
    """
    Может ли user видеть данные этого Student вообще - либо родитель,
    либо учитель хотя бы одного его активного Enrollment.
    """
    from django.db.models import Q

    if user_is_parent_of(user, student):
        return True
    return Enrollment.objects.filter(
        student=student,
        status=Enrollment.STATUS_ACTIVE,
    ).filter(
        Q(group__teacher=user) | Q(teacher=user)
    ).exists()