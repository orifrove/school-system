from django.contrib import admin

from .models import (
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


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "birth_date", "is_active")
    list_filter = ("is_active",)
    search_fields = ("full_name",)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active")
    search_fields = ("name",)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "subject", "teacher", "capacity", "is_active")
    list_filter = ("subject", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ("subject", "teacher")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "group", "subject", "teacher", "status", "start_date", "end_date")
    list_filter = ("status",)
    search_fields = ("student__full_name",)
    autocomplete_fields = ("student", "group", "subject", "teacher")




@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("id", "group", "enrollment", "weekday", "start_time", "end_time", "is_active")
    list_filter = ("weekday", "is_active")
    search_fields = ("group__name",)
    autocomplete_fields = ("group", "enrollment")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "teacher", "starts_at", "status")
    list_filter = ("status", "subject")
    autocomplete_fields = ("schedule", "teacher", "subject")
    search_fields = ("subject__name",)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("id", "lesson", "student", "status", "marked_at")
    list_filter = ("status",)
    autocomplete_fields = ("lesson", "student", "marked_by")


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("id", "enrollment", "value", "given_by_teacher", "given_at")
    autocomplete_fields = ("enrollment", "lesson", "given_by_teacher")


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