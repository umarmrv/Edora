from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import ModelForm
from django.urls import path
from django.utils.html import format_html

from crm.admin_views import cycle_finance_summary_view, teacher_performance_view
from crm.models import (
    AttendanceRecord,
    BillingCycle,
    GroupEnrollment,
    GroupSchedule,
    Lesson,
    Payment,
    PlacementTest,
    StudyGroup,
    Subject,
    TestAttempt,
    User,
    UserExitRecord,
)

try:
    from unfold.admin import ModelAdmin
except ImportError:  # pragma: no cover
    from django.contrib.admin import ModelAdmin


def is_super_admin(user: User) -> bool:
    return bool(user.is_authenticated and (user.is_superuser or user.role == User.Role.SUPER_ADMIN))


def is_center_admin(user: User) -> bool:
    return bool(user.is_authenticated and user.role == User.Role.CENTER_ADMIN)


class UserExitRecordForm(ModelForm):
    class Meta:
        model = UserExitRecord
        fields = "__all__"

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Причина выбытия обязательна.")
        return reason


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "full_name",
        "role",
        "is_active_in_center",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "is_active_in_center", "is_staff", "is_active")
    search_fields = ("username", "first_name", "last_name", "middle_name", "phone_student", "phone_parent")
    ordering = ("username",)

    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Профиль центра",
            {
                "fields": (
                    "role",
                    "middle_name",
                    "phone_student",
                    "phone_parent",
                    "address",
                    "photo",
                    "school_name",
                    "school_shift",
                    "joined_center_at",
                    "is_active_in_center",
                )
            },
        ),
    )

    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "Профиль центра",
            {
                "fields": (
                    "role",
                    "middle_name",
                    "phone_student",
                    "phone_parent",
                    "address",
                    "photo",
                    "school_name",
                    "school_shift",
                )
            },
        ),
    )

    def _filter_fieldsets(self, fieldsets, forbidden_fields: set[str]):
        filtered = []
        for section, options in fieldsets:
            fields = options.get("fields", ())
            updated_fields = []
            for field in fields:
                if isinstance(field, (tuple, list)):
                    nested = tuple(item for item in field if item not in forbidden_fields)
                    if nested:
                        updated_fields.append(nested)
                elif field not in forbidden_fields:
                    updated_fields.append(field)

            if updated_fields:
                filtered.append((section, {**options, "fields": tuple(updated_fields)}))
        return tuple(filtered)

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        forbidden_fields = {"groups", "user_permissions"}
        if is_center_admin(request.user):
            forbidden_fields.update({"is_superuser", "is_staff"})
        return self._filter_fieldsets(fieldsets, forbidden_fields)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "role" in form.base_fields and is_center_admin(request.user):
            form.base_fields["role"].choices = [
                (User.Role.TEACHER, User.Role.TEACHER.label),
                (User.Role.STUDENT, User.Role.STUDENT.label),
            ]
        return form

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if is_super_admin(request.user):
            return queryset
        if is_center_admin(request.user):
            return queryset.filter(role__in=[User.Role.TEACHER, User.Role.STUDENT], is_active_in_center=True)
        return queryset.none()

    def has_module_permission(self, request):
        return is_super_admin(request.user) or is_center_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_super_admin(request.user) or is_center_admin(request.user)

    def has_add_permission(self, request):
        return is_super_admin(request.user) or is_center_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_super_admin(request.user)

    def save_model(self, request, obj, form, change):
        if is_center_admin(request.user) and obj.role not in {User.Role.TEACHER, User.Role.STUDENT}:
            raise PermissionDenied("Администрация центра может создавать только Учителей и Студентов.")

        if obj.role == User.Role.STUDENT:
            obj.is_staff = False
            obj.is_superuser = False
        elif obj.role == User.Role.TEACHER:
            obj.is_staff = True
            obj.is_superuser = False
        elif obj.role == User.Role.CENTER_ADMIN:
            obj.is_staff = True
            obj.is_superuser = False
        elif obj.role == User.Role.SUPER_ADMIN:
            obj.is_staff = True
            obj.is_superuser = True

        super().save_model(request, obj, form, change)

        if obj.role in {User.Role.STUDENT, User.Role.TEACHER, User.Role.CENTER_ADMIN}:
            obj.groups.clear()
            obj.user_permissions.clear()


@admin.register(Subject)
class SubjectAdmin(ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


class GroupScheduleInline(admin.TabularInline):
    model = GroupSchedule
    extra = 1


@admin.register(StudyGroup)
class StudyGroupAdmin(ModelAdmin):
    list_display = ("name", "subject", "level", "teacher", "cycle_price", "is_active")
    list_filter = ("subject", "is_active")
    search_fields = ("name", "level", "subject__name")
    inlines = [GroupScheduleInline]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if getattr(request.user, "role", None) == User.Role.TEACHER:
            return queryset.filter(teacher=request.user, is_active=True)
        if getattr(request.user, "role", None) == User.Role.STUDENT:
            return queryset.filter(enrollments__student=request.user, enrollments__is_active=True).distinct()
        return queryset


@admin.register(GroupEnrollment)
class GroupEnrollmentAdmin(ModelAdmin):
    list_display = ("group", "student", "started_at", "is_active")
    list_filter = ("group", "is_active")
    search_fields = ("group__name", "student__first_name", "student__last_name", "student__username")


@admin.register(Lesson)
class LessonAdmin(ModelAdmin):
    list_display = ("topic", "group", "starts_at")
    list_filter = ("group", "group__subject")
    search_fields = ("topic", "group__name", "group__subject__name")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if getattr(request.user, "role", None) == User.Role.TEACHER:
            return queryset.filter(group__teacher=request.user)
        if getattr(request.user, "role", None) == User.Role.STUDENT:
            return queryset.filter(group__enrollments__student=request.user, group__enrollments__is_active=True).distinct()
        return queryset


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(ModelAdmin):
    list_display = ("lesson", "student", "status", "activity_score", "homework_score", "exam_score")
    list_filter = ("status", "lesson__group", "lesson__group__subject")
    search_fields = ("student__first_name", "student__last_name", "lesson__group__name")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if getattr(request.user, "role", None) == User.Role.TEACHER:
            return queryset.filter(lesson__group__teacher=request.user)
        if getattr(request.user, "role", None) == User.Role.STUDENT:
            return queryset.filter(student=request.user)
        return queryset


@admin.register(BillingCycle)
class BillingCycleAdmin(ModelAdmin):
    list_display = ("group", "number", "opened_at", "lesson_start_number", "lesson_end_number")
    list_filter = ("group__subject", "group")


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = (
        "student",
        "cycle",
        "amount_due",
        "amount_paid",
        "amount_remaining",
        "status_badge",
    )
    list_filter = ("status", "cycle__group__subject", "cycle__group")
    search_fields = ("student__first_name", "student__last_name", "student__username", "cycle__group__name")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if getattr(request.user, "role", None) == User.Role.TEACHER:
            return queryset.none()
        if getattr(request.user, "role", None) == User.Role.STUDENT:
            return queryset.filter(student=request.user)
        return queryset

    @admin.display(description="Статус")
    def status_badge(self, obj: Payment):
        colors = {
            Payment.Status.PAID: "#18794e",
            Payment.Status.PARTIAL: "#b86900",
            Payment.Status.UNPAID: "#b42318",
        }
        color = colors.get(obj.status, "#344054")
        return format_html(
            '<span style="padding:3px 8px;border-radius:999px;background:{};color:white;">{}</span>',
            color,
            obj.get_status_display(),
        )


@admin.register(UserExitRecord)
class UserExitRecordAdmin(ModelAdmin):
    form = UserExitRecordForm
    list_display = ("user", "removed_by", "exited_at")
    search_fields = ("user__first_name", "user__last_name", "user__username", "reason")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if is_super_admin(request.user):
            return queryset
        if is_center_admin(request.user):
            return queryset.none()
        return queryset.none()

    def has_module_permission(self, request):
        return is_super_admin(request.user) or is_center_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_super_admin(request.user)

    def has_add_permission(self, request):
        return is_super_admin(request.user) or is_center_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_super_admin(request.user)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.removed_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(PlacementTest)
class PlacementTestAdmin(ModelAdmin):
    list_display = ("title", "target_role", "question_count", "is_active")
    list_filter = ("target_role", "is_active")


@admin.register(TestAttempt)
class TestAttemptAdmin(ModelAdmin):
    list_display = ("user", "test", "correct_answers", "total_questions", "score_percent", "level", "taken_at")
    list_filter = ("test__target_role", "level", "is_final")
    search_fields = ("user__first_name", "user__last_name", "user__username", "test__title")


original_get_urls = admin.site.get_urls


def custom_admin_urls():
    urls = original_get_urls()
    custom_urls = [
        path(
            "crm/reports/teacher-performance/",
            admin.site.admin_view(teacher_performance_view),
            name="crm_teacher_performance",
        ),
        path(
            "crm/reports/cycle-finance-summary/",
            admin.site.admin_view(cycle_finance_summary_view),
            name="crm_cycle_finance_summary",
        ),
    ]
    return custom_urls + urls


admin.site.get_urls = custom_admin_urls
admin.site.site_header = "Edora CRM"
admin.site.site_title = "Edora CRM"
admin.site.index_title = "Управление учебным центром"
