from django.contrib import admin
from django.db import transaction
from django.db.models import Count, Q

from .forms import GroupAdminForm, ParentStudentAdminForm, ScheduleAdminForm
from .services import change_group_teacher, update_group

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
    list_display = ("id", "subject", "teacher", "starts_at", "status")
    list_filter = ("status", "subject")
    autocomplete_fields = ("schedule", "teacher", "subject")
    search_fields = ("subject__name",)
    date_hierarchy = "starts_at"
    ordering = ("-starts_at", "-pk")
    list_select_related = ("subject", "teacher")


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
