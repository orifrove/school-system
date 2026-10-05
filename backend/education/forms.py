from django import forms

from education.models import Group, ParentStudent, Schedule
from users.models import Role


class ParentStudentAdminForm(forms.ModelForm):
    class Meta:
        model = ParentStudent
        fields = "__all__"

    def clean_parent(self):
        parent = self.cleaned_data["parent"]
        if self.instance._state.adding or "parent" in self.changed_data:
            if not parent.is_active or not parent.user_roles.filter(role__code=Role.PARENT).exists():
                raise forms.ValidationError("У выбранного пользователя должна быть активная учётная запись и роль Parent.")
        return parent


class GroupAdminForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = "__all__"

    def clean_teacher(self):
        teacher = self.cleaned_data["teacher"]
        if self.instance._state.adding or "teacher" in self.changed_data:
            if not teacher.is_active or not teacher.user_roles.filter(role__code=Role.TEACHER).exists():
                raise forms.ValidationError("Назначьте активного пользователя с ролью Teacher.")
        return teacher

    def clean_subject(self):
        subject = self.cleaned_data["subject"]
        if self.instance.pk and "subject" in self.changed_data:
            if self.instance.enrollments.exists() or self.instance.schedules.exists():
                raise forms.ValidationError("У группы есть учебная история. Для другого предмета создайте новую группу.")
        return subject


class ScheduleAdminForm(forms.ModelForm):
    class Meta:
        model = Schedule
        fields = "__all__"

    def clean(self):
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        if start is not None and end is not None and end <= start:
            self.add_error("end_time", "Окончание должно быть позже начала.")
        first, last = data.get("valid_from"), data.get("valid_until")
        if first and last and last < first:
            self.add_error("valid_until", "Дата окончания не может предшествовать дате начала.")
        enrollment = data.get("enrollment")
        if enrollment is not None and enrollment.group_id is not None:
            self.add_error("enrollment", "Для группы используйте поле Group. Enrollment здесь — только индивидуальный.")
        return data
