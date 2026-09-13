from django.contrib import admin

from .models import Enrollment, Group, Student, Subject


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
    autocomplete_fields = ("student", "group", "subject", "teacher")