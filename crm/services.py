from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from crm.models import BillingCycle, Lesson, Payment


@dataclass
class TeacherPerformanceRow:
    teacher_id: int
    teacher_name: str
    lessons_count: int
    active_groups: int
    students_total: int


@dataclass
class DebtorRow:
    student_name: str
    group_name: str
    subject_name: str
    debt_amount: Decimal


@dataclass
class CycleFinanceSummary:
    total_due: Decimal
    total_paid: Decimal
    total_partial_paid: Decimal
    total_debt: Decimal
    paid_ratio: Decimal
    debtors: list[DebtorRow]
    subject_breakdown: list[dict]


def _decimal(value: Decimal | None) -> Decimal:
    return value or Decimal("0.00")


def teacher_performance_report(
    start_date: date,
    end_date: date,
    subject_id: int | None = None,
    group_id: int | None = None,
) -> list[TeacherPerformanceRow]:
    lessons = Lesson.objects.filter(starts_at__date__gte=start_date, starts_at__date__lte=end_date)

    if subject_id:
        lessons = lessons.filter(group__subject_id=subject_id)
    if group_id:
        lessons = lessons.filter(group_id=group_id)

    rows = (
        lessons.filter(group__teacher__isnull=False)
        .values(
            "group__teacher_id",
            "group__teacher__first_name",
            "group__teacher__last_name",
            "group__teacher__middle_name",
        )
        .annotate(
            lessons_count=Count("id", distinct=True),
            active_groups=Count("group", distinct=True),
            students_total=Count(
                "group__enrollments__student",
                filter=Q(group__enrollments__is_active=True),
                distinct=True,
            ),
        )
        .order_by("-lessons_count", "group__teacher__last_name")
    )

    result: list[TeacherPerformanceRow] = []
    for row in rows:
        teacher_name = " ".join(
            p
            for p in [
                row["group__teacher__last_name"],
                row["group__teacher__first_name"],
                row["group__teacher__middle_name"],
            ]
            if p
        )
        result.append(
            TeacherPerformanceRow(
                teacher_id=row["group__teacher_id"],
                teacher_name=teacher_name,
                lessons_count=row["lessons_count"],
                active_groups=row["active_groups"],
                students_total=row["students_total"],
            )
        )

    return result


def cycle_finance_report(
    start_date: date,
    end_date: date,
    subject_id: int | None = None,
    group_id: int | None = None,
) -> CycleFinanceSummary:
    cycles = BillingCycle.objects.filter(opened_at__date__gte=start_date, opened_at__date__lte=end_date)

    if subject_id:
        cycles = cycles.filter(group__subject_id=subject_id)
    if group_id:
        cycles = cycles.filter(group_id=group_id)

    payments = Payment.objects.filter(cycle__in=cycles).select_related(
        "student", "cycle__group", "cycle__group__subject"
    )

    totals = payments.aggregate(
        total_due=Coalesce(Sum("amount_due"), Value(Decimal("0.00"))),
        total_paid=Coalesce(Sum("amount_paid"), Value(Decimal("0.00"))),
        total_partial_paid=Coalesce(
            Sum("amount_paid", filter=Q(status=Payment.Status.PARTIAL)),
            Value(Decimal("0.00")),
        ),
    )

    total_due = _decimal(totals["total_due"])
    total_paid = _decimal(totals["total_paid"])
    total_partial_paid = _decimal(totals["total_partial_paid"])
    total_debt = total_due - total_paid
    if total_debt < 0:
        total_debt = Decimal("0.00")

    if total_due == 0:
        paid_ratio = Decimal("0.00")
    else:
        paid_ratio = (total_paid / total_due * Decimal("100")).quantize(Decimal("0.01"))

    debtors_qs = (
        payments.annotate(debt_amount=F("amount_due") - F("amount_paid"))
        .filter(debt_amount__gt=0)
        .order_by("cycle__group__subject__name", "cycle__group__name", "student__last_name", "student__first_name")
    )

    debtors = [
        DebtorRow(
            student_name=p.student.full_name,
            group_name=p.cycle.group.name,
            subject_name=p.cycle.group.subject.name,
            debt_amount=p.debt_amount,
        )
        for p in debtors_qs
    ]

    subject_breakdown_qs = (
        payments.values("cycle__group__subject__name")
        .annotate(
            due=Coalesce(Sum("amount_due"), Value(Decimal("0.00"))),
            paid=Coalesce(Sum("amount_paid"), Value(Decimal("0.00"))),
        )
        .order_by("cycle__group__subject__name")
    )

    subject_breakdown = []
    for row in subject_breakdown_qs:
        debt = row["due"] - row["paid"]
        if debt < 0:
            debt = Decimal("0.00")
        subject_breakdown.append(
            {
                "subject_name": row["cycle__group__subject__name"],
                "due": row["due"],
                "paid": row["paid"],
                "debt": debt,
            }
        )

    return CycleFinanceSummary(
        total_due=total_due,
        total_paid=total_paid,
        total_partial_paid=total_partial_paid,
        total_debt=total_debt,
        paid_ratio=paid_ratio,
        debtors=debtors,
        subject_breakdown=subject_breakdown,
    )
