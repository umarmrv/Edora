from __future__ import annotations

from datetime import date, timedelta

from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from crm.models import StudyGroup, Subject, User
from crm.services import cycle_finance_report, teacher_performance_report

PERIOD_DAY = "day"
PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIOD_CUSTOM = "custom"


def _is_super_admin(user: User) -> bool:
    return bool(user and user.is_authenticated and (user.is_superuser or user.role == User.Role.SUPER_ADMIN))


def _ensure_super_admin(request: HttpRequest) -> None:
    if not _is_super_admin(request.user):
        raise PermissionDenied("Этот раздел доступен только Супер-админу.")


def _resolve_period(request: HttpRequest) -> tuple[date, date, str]:
    period = request.GET.get("period", PERIOD_MONTH)
    today = timezone.localdate()

    if period == PERIOD_DAY:
        return today, today, period

    if period == PERIOD_WEEK:
        start = today - timedelta(days=6)
        return start, today, period

    if period == PERIOD_CUSTOM:
        start_str = request.GET.get("start_date")
        end_str = request.GET.get("end_date")
        start = parse_date(start_str) if start_str else None
        end = parse_date(end_str) if end_str else None
        if start and end and start <= end:
            return start, end, period
        messages.warning(request, "Неверный пользовательский период, применен период за текущий месяц.")

    start_of_month = today.replace(day=1)
    return start_of_month, today, PERIOD_MONTH


def teacher_performance_view(request: HttpRequest) -> HttpResponse:
    _ensure_super_admin(request)

    start_date, end_date, period = _resolve_period(request)
    subject_id = request.GET.get("subject")
    group_id = request.GET.get("group")

    subject_value = int(subject_id) if subject_id and subject_id.isdigit() else None
    group_value = int(group_id) if group_id and group_id.isdigit() else None

    rows = teacher_performance_report(
        start_date=start_date,
        end_date=end_date,
        subject_id=subject_value,
        group_id=group_value,
    )

    total_lessons = sum(row.lessons_count for row in rows)

    context = {
        **admin.site.each_context(request),
        "title": "Статистика учителей",
        "rows": rows,
        "total_lessons": total_lessons,
        "subjects": Subject.objects.filter(is_active=True),
        "groups": StudyGroup.objects.filter(is_active=True).select_related("subject"),
        "selected_subject": subject_value,
        "selected_group": group_value,
        "selected_period": period,
        "start_date": start_date,
        "end_date": end_date,
        "finance_url": reverse("admin:crm_cycle_finance_summary"),
    }
    return TemplateResponse(request, "admin/crm/teacher_performance.html", context)


def cycle_finance_summary_view(request: HttpRequest) -> HttpResponse:
    _ensure_super_admin(request)

    start_date, end_date, period = _resolve_period(request)
    subject_id = request.GET.get("subject")
    group_id = request.GET.get("group")

    subject_value = int(subject_id) if subject_id and subject_id.isdigit() else None
    group_value = int(group_id) if group_id and group_id.isdigit() else None

    summary = cycle_finance_report(
        start_date=start_date,
        end_date=end_date,
        subject_id=subject_value,
        group_id=group_value,
    )

    context = {
        **admin.site.each_context(request),
        "title": "Финансы по циклам",
        "summary": summary,
        "subjects": Subject.objects.filter(is_active=True),
        "groups": StudyGroup.objects.filter(is_active=True).select_related("subject"),
        "selected_subject": subject_value,
        "selected_group": group_value,
        "selected_period": period,
        "start_date": start_date,
        "end_date": end_date,
        "teacher_stats_url": reverse("admin:crm_teacher_performance"),
    }
    return TemplateResponse(request, "admin/crm/cycle_finance_summary.html", context)
