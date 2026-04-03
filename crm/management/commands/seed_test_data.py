from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from crm.models import (
    GroupEnrollment,
    Lesson,
    Payment,
    PlacementTest,
    StudyGroup,
    Subject,
    TestAttempt,
    User,
    UserExitRecord,
)


class Command(BaseCommand):
    help = "Create demo/test data for Edora CRM analytics and admin flows"

    @transaction.atomic
    def handle(self, *args, **options):
        super_admin = self._upsert_user(
            username="superadmin",
            password="superadmin123",
            role=User.Role.SUPER_ADMIN,
            first_name="Super",
            last_name="Admin",
            is_staff=True,
            is_superuser=True,
        )
        center_admin = self._upsert_user(
            username="centeradmin",
            password="centeradmin123",
            role=User.Role.CENTER_ADMIN,
            first_name="Center",
            last_name="Manager",
            is_staff=True,
        )

        teachers = [
            self._upsert_user(
                username="teacher_rus",
                password="teacher123",
                role=User.Role.TEACHER,
                first_name="Madina",
                last_name="Rasulova",
                is_staff=True,
            ),
            self._upsert_user(
                username="teacher_eng",
                password="teacher123",
                role=User.Role.TEACHER,
                first_name="Ali",
                last_name="Karimov",
                is_staff=True,
            ),
            self._upsert_user(
                username="teacher_chi",
                password="teacher123",
                role=User.Role.TEACHER,
                first_name="Said",
                last_name="Zokirov",
                is_staff=True,
            ),
            self._upsert_user(
                username="teacher_it",
                password="teacher123",
                role=User.Role.TEACHER,
                first_name="Dilorom",
                last_name="Yusupova",
                is_staff=True,
            ),
        ]

        students = []
        for index in range(1, 13):
            students.append(
                self._upsert_user(
                    username=f"student{index}",
                    password="student123",
                    role=User.Role.STUDENT,
                    first_name=f"Student{index}",
                    last_name="Testov",
                    phone_student=f"+992900000{index:02d}",
                    school_name="School #1",
                )
            )

        subjects = {
            "russian": Subject.objects.get_or_create(name="Русский", defaults={"is_active": True})[0],
            "english": Subject.objects.get_or_create(name="Английский", defaults={"is_active": True})[0],
            "chinese": Subject.objects.get_or_create(name="Китайский", defaults={"is_active": True})[0],
            "informatics": Subject.objects.get_or_create(name="Информатика", defaults={"is_active": True})[0],
        }

        groups = {
            "russian": self._upsert_group(subjects["russian"], "RUS-A1", "A1", Decimal("1200.00"), teachers[0]),
            "english": self._upsert_group(subjects["english"], "ENG-B1", "B1", Decimal("1400.00"), teachers[1]),
            "chinese": self._upsert_group(subjects["chinese"], "HSK2", "HSK2", Decimal("1600.00"), teachers[2]),
            "informatics": self._upsert_group(subjects["informatics"], "IT-BASE", "BASE", Decimal("1800.00"), teachers[3]),
        }

        enrollment_map = {
            "russian": students[0:4],
            "english": students[3:7],
            "chinese": students[6:10],
            "informatics": students[9:12],
        }

        for key, group_students in enrollment_map.items():
            self._ensure_enrollments(groups[key], group_students)

        # Generate enough lessons to open billing cycles.
        self._ensure_lessons(groups["russian"], 24)
        self._ensure_lessons(groups["english"], 12)
        self._ensure_lessons(groups["chinese"], 12)
        self._ensure_lessons(groups["informatics"], 8)

        # Payment patterns for debts and partial payments.
        self._adjust_payment_samples(groups["russian"], Decimal("1200.00"), Decimal("600.00"))
        self._adjust_payment_samples(groups["english"], Decimal("1400.00"), Decimal("700.00"))

        # Placement tests and attempts.
        student_test = self._upsert_test("Тест уровня ученика", User.Role.STUDENT)
        teacher_test = self._upsert_test("Тест уровня учителя", User.Role.TEACHER)

        self._upsert_attempt(students[0], student_test, correct_answers=82)
        self._upsert_attempt(students[1], student_test, correct_answers=54)
        self._upsert_attempt(teachers[0], teacher_test, correct_answers=90)
        self._upsert_attempt(teachers[1], teacher_test, correct_answers=68)

        # One exited student for super-admin movement stats.
        exited_student = students[-1]
        if not hasattr(exited_student, "exit_record"):
            UserExitRecord.objects.create(
                user=exited_student,
                reason="Переезд в другой город",
                removed_by=center_admin,
            )

        self.stdout.write(self.style.SUCCESS("Demo data created/updated successfully."))
        self.stdout.write(
            "Super admin: superadmin / superadmin123 | Center admin: centeradmin / centeradmin123"
        )

    def _upsert_user(self, username: str, password: str, role: str, **defaults) -> User:
        user, _ = User.objects.get_or_create(username=username, defaults={"role": role, **defaults})

        changed = False
        if user.role != role:
            user.role = role
            changed = True

        for field, value in defaults.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed = True

        if not user.check_password(password):
            user.set_password(password)
            changed = True

        if changed:
            user.save()

        return user

    def _upsert_group(
        self,
        subject: Subject,
        name: str,
        level: str,
        cycle_price: Decimal,
        teacher: User,
    ) -> StudyGroup:
        group, _ = StudyGroup.objects.update_or_create(
            subject=subject,
            name=name,
            defaults={
                "level": level,
                "course_duration_weeks": 12,
                "cycle_price": cycle_price,
                "teacher": teacher,
                "is_active": True,
            },
        )
        return group

    def _ensure_enrollments(self, group: StudyGroup, students: list[User]) -> None:
        for student in students:
            GroupEnrollment.objects.get_or_create(
                group=group,
                student=student,
                defaults={"is_active": True},
            )

    def _ensure_lessons(self, group: StudyGroup, target_count: int) -> None:
        existing = group.lessons.count()
        if existing >= target_count:
            return

        start_time = timezone.now() - timedelta(days=target_count)
        for index in range(existing, target_count):
            Lesson.objects.create(
                group=group,
                topic=f"{group.name} Lesson {index + 1}",
                starts_at=start_time + timedelta(days=index),
                homework="Домашнее задание",
            )

    def _adjust_payment_samples(self, group: StudyGroup, full_amount: Decimal, partial_amount: Decimal) -> None:
        payments = (
            Payment.objects.filter(cycle__group=group)
            .order_by("cycle__number", "student__username")
            .select_related("student")
        )
        if not payments:
            return

        first_cycle_payments = [payment for payment in payments if payment.cycle.number == 1]
        if len(first_cycle_payments) >= 1:
            first_cycle_payments[0].amount_paid = full_amount
            first_cycle_payments[0].save()
        if len(first_cycle_payments) >= 2:
            first_cycle_payments[1].amount_paid = partial_amount
            first_cycle_payments[1].save()

    def _upsert_test(self, title: str, role: str) -> PlacementTest:
        test, _ = PlacementTest.objects.update_or_create(
            title=title,
            defaults={
                "target_role": role,
                "question_count": 100,
                "is_active": True,
            },
        )
        return test

    def _upsert_attempt(self, user: User, test: PlacementTest, correct_answers: int) -> None:
        TestAttempt.objects.update_or_create(
            user=user,
            test=test,
            defaults={
                "total_questions": 100,
                "correct_answers": correct_answers,
                "is_final": True,
            },
        )
