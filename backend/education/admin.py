from django.contrib import admin
from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils import timezone

from .forms import GroupAdminForm, LessonAdminForm, ParentStudentAdminForm, ScheduleAdminForm
from .services import change_group_teacher, update_group
from .lesson_lock import lock_lesson_planning
from .admin_filters import LessonPeriodFilter

from .models import (
    Answer,
    Attendance,
    Enrollment,
    Grade,
    Group,
    Lesson,
    ParentStudent,
    Question,
    Schedule,
    Student,
    Subject,
)


class ParentStudentInline(admin.TabularInline):
    model = ParentStudent
    form = ParentStudentAdminForm
    extra = 0
    autocomplete_fields = ("parent",)
    fields = ("parent", "relation", "created_at")
    readonly_fields = ("created_at",)


class EnrollmentHistoryInline(admin.TabularInline):
    model = Enrollment
    extra = 0
    fields = ("student", "group", "subject", "teacher", "status", "start_date", "end_date")
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("student", "group", "subject", "teacher")


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "birth_date", "is_active", "active_enrollments")
    list_filter = ("is_active",)
    search_fields = ("full_name",)
    inlines = (ParentStudentInline, EnrollmentHistoryInline)
    ordering = ("full_name", "pk")
    list_per_page = 30

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(active_count=Count("enrollments",
            filter=Q(enrollments__status=Enrollment.STATUS_ACTIVE), distinct=True))

    @admin.display(description="Активных зачислений", ordering="active_count")
    def active_enrollments(self, obj):
        return obj.active_count


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active")
    search_fields = ("name",)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    @transaction.atomic
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST":
            lock_lesson_planning()
        return super().changeform_view(request, object_id, form_url, extra_context)

    form = GroupAdminForm
    list_display = ("id", "name", "subject", "teacher", "capacity", "is_active")
    list_filter = ("subject", "is_active")
    search_fields = ("name", "teacher__full_name", "subject__name")
    autocomplete_fields = ("subject", "teacher")
    list_select_related = ("subject", "teacher")
    inlines = (EnrollmentHistoryInline,)
    list_per_page = 30

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
            return
        lock_lesson_planning()
        original = Group.objects.select_for_update().get(pk=obj.pk)
        update_group(original, name=obj.name, subject=obj.subject,
                     capacity=obj.capacity, is_active=obj.is_active)
        if original.teacher_id != obj.teacher_id:
            change_group_teacher(original, obj.teacher)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "group", "subject", "teacher", "status", "start_date", "end_date")
    list_filter = ("status",)
    search_fields = ("student__full_name",)
    autocomplete_fields = ("student", "group", "subject", "teacher")
    list_select_related = ("student", "group", "subject", "teacher")
    list_per_page = 30




@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    form = ScheduleAdminForm
    list_display = ("id", "group", "enrollment", "weekday", "start_time", "end_time", "is_active")
    list_filter = ("weekday", "is_active")
    search_fields = ("group__name", "enrollment__student__full_name")
    autocomplete_fields = ("group", "enrollment")
    list_select_related = ("group", "enrollment__student", "enrollment__group", "enrollment__subject")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    form = LessonAdminForm

    @transaction.atomic
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST":
            # Lock before form validation and hold until Admin finishes saving.
            lock_lesson_planning()
        return super().changeform_view(request, object_id, form_url, extra_context)

    list_display = ("id", "learning_source", "subject", "teacher", "starts_at", "ends_at", "room", "status", "attendance_count", "grade_count")
    list_filter = (LessonPeriodFilter, "status", "subject", ("teacher", admin.RelatedOnlyFieldListFilter))
    autocomplete_fields = ("schedule", "teacher", "subject")
    search_fields = ("subject__name", "teacher__full_name", "schedule__group__name",
                     "schedule__enrollment__student__full_name", "room")
    search_help_text = "Предмет, преподаватель, группа, индивидуальный ученик или кабинет."
    date_hierarchy = "starts_at"
    ordering = ("-starts_at", "-pk")
    list_per_page = 30
    list_select_related = ("subject", "teacher", "schedule__group", "schedule__enrollment__student")

    @staticmethod
    def can_view_records(request, model):
        return request.user.has_perm(f"education.view_{model}") or request.user.has_perm(f"education.change_{model}")

    def get_list_display(self, request):
        fields = list(super().get_list_display(request))
        for model, field in (("attendance", "attendance_count"), ("grade", "grade_count")):
            if not self.can_view_records(request, model):
                fields.remove(field)
        return fields

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        annotations = {}
        if self.can_view_records(request, "attendance"):
            annotations["attendance_total"] = Count("attendances", distinct=True)
        if self.can_view_records(request, "grade"):
            annotations["grade_total"] = Count("grades", distinct=True)
        return queryset.annotate(**annotations)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            if self.can_view_records(request, "attendance"):
                fields.append("attendance_journal")
            if self.can_view_records(request, "grade"):
                fields.append("grade_journal")
        return fields

    @admin.display(description="Отметок", ordering="attendance_total")
    def attendance_count(self, obj):
        return obj.attendance_total

    @admin.display(description="Оценок", ordering="grade_total")
    def grade_count(self, obj):
        return obj.grade_total

    @admin.display(description="Посещаемость занятия")
    def attendance_journal(self, obj):
        rows = list(obj.attendances.select_related("student", "marked_by").order_by("student__full_name", "pk")[:20])
        if not rows:
            return "Отметок пока нет."
        body = format_html_join("", "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", (
            (row.student.full_name, row.get_status_display(), row.comment or "—",
             row.marked_by.full_name if row.marked_by else "—") for row in rows))
        return format_html('<p>Первые 20 записей. <a href="{}?lesson__id__exact={}">Все отметки этого занятия</a></p>'
            '<table><thead><tr><th>Ученик</th><th>Отметка</th><th>Комментарий</th><th>Автор</th></tr></thead><tbody>{}</tbody></table>',
            reverse("admin:education_attendance_changelist"), obj.pk, body)

    @admin.display(description="Оценки занятия")
    def grade_journal(self, obj):
        rows = list(obj.grades.select_related("enrollment__student", "given_by_teacher").order_by("-given_at", "-pk")[:20])
        if not rows:
            return "Оценок пока нет."
        body = format_html_join("", "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", (
            (row.enrollment.student.full_name, f"{row.value}/{row.max_value}" if row.max_value else row.value, row.comment or "—", row.given_by_teacher.full_name,
             timezone.localtime(row.given_at, timezone.get_default_timezone()).strftime("%d.%m.%Y %H:%M")) for row in rows))
        return format_html('<p>Последние 20 записей. <a href="{}?lesson__id__exact={}">Все оценки этого занятия</a></p>'
            '<table><thead><tr><th>Ученик</th><th>Оценка</th><th>Комментарий</th><th>Автор</th><th>Дата</th></tr></thead><tbody>{}</tbody></table>',
            reverse("admin:education_grade_changelist"), obj.pk, body)

    def get_ordering(self, request):
        if request.GET.get("lesson_period") in {"today", "tomorrow", "week"}:
            return ("starts_at", "pk")
        return super().get_ordering(request)

    @admin.display(description="Группа / индивидуально")
    def learning_source(self, obj):
        if obj.schedule.group_id:
            return obj.schedule.group.name
        return f"Индивидуально: {obj.schedule.enrollment.student.full_name}"


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("id", "lesson", "student", "status", "marked_at")
    list_filter = ("status",)
    autocomplete_fields = ("lesson", "student", "marked_by")
    search_fields = ("student__full_name", "lesson__subject__name")
    list_select_related = ("lesson__subject", "student")
    date_hierarchy = "lesson__starts_at"


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("id", "enrollment", "value", "given_by_teacher", "given_at")
    autocomplete_fields = ("enrollment", "lesson", "given_by_teacher")
    search_fields = ("enrollment__student__full_name", "given_by_teacher__full_name")
    list_select_related = ("enrollment__student", "enrollment__group", "enrollment__subject", "given_by_teacher")
    date_hierarchy = "given_at"
    ordering = ("-given_at", "-pk")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "parent", "student", "teacher", "answered", "created_at")
    list_filter = ("answered",)
    search_fields = ("student__full_name",)
    autocomplete_fields = ("parent", "student", "teacher")


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ("id", "question", "answered_by", "created_at")
    autocomplete_fields = ("question", "answered_by")

    

@admin.register(ParentStudent)
class ParentStudentAdmin(admin.ModelAdmin):
    form = ParentStudentAdminForm
    list_display = ("id", "parent", "student", "relation")
    list_filter = ("relation",)
    autocomplete_fields = ("parent", "student")
    search_fields = ("parent__full_name", "student__full_name")
    list_select_related = ("parent", "student")
