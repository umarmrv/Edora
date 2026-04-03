from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from crm.models import AttendanceRecord, BillingCycle, GroupEnrollment, Lesson, Payment, UserExitRecord

LESSONS_PER_CYCLE = 12


@receiver(post_save, sender=Lesson)
def lesson_created_handler(sender, instance: Lesson, created: bool, **kwargs):
    if not created:
        return

    active_enrollments = GroupEnrollment.objects.filter(
        group=instance.group,
        is_active=True,
        student__is_active_in_center=True,
    ).select_related("student")

    attendance_records = [
        AttendanceRecord(lesson=instance, student=enrollment.student)
        for enrollment in active_enrollments
    ]
    AttendanceRecord.objects.bulk_create(attendance_records, ignore_conflicts=True)

    lesson_count = Lesson.objects.filter(group=instance.group).count()
    if lesson_count % LESSONS_PER_CYCLE != 0:
        return

    cycle_number = lesson_count // LESSONS_PER_CYCLE
    cycle, cycle_created = BillingCycle.objects.get_or_create(
        group=instance.group,
        number=cycle_number,
        defaults={
            "lesson_start_number": lesson_count - LESSONS_PER_CYCLE + 1,
            "lesson_end_number": lesson_count,
        },
    )

    if not cycle_created:
        return

    payments = [
        Payment(
            cycle=cycle,
            student=enrollment.student,
            amount_due=instance.group.cycle_price,
        )
        for enrollment in active_enrollments
    ]
    Payment.objects.bulk_create(payments, ignore_conflicts=True)


@receiver(post_save, sender=UserExitRecord)
def user_exit_handler(sender, instance: UserExitRecord, created: bool, **kwargs):
    if not created:
        return

    user = instance.user
    user.is_active_in_center = False
    user.is_active = False
    user.save(update_fields=["is_active_in_center", "is_active"])
