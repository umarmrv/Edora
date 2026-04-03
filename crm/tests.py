from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from crm.models import BillingCycle, GroupEnrollment, Lesson, Payment, PlacementTest, StudyGroup, Subject, TestAttempt
from crm.services import cycle_finance_report, teacher_performance_report

User = get_user_model()


class CRMAnalyticsTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username="super",
            password="pass12345",
            role=User.Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
            first_name="Super",
            last_name="Admin",
        )
        self.center_admin = User.objects.create_user(
            username="admin",
            password="pass12345",
            role=User.Role.CENTER_ADMIN,
            is_staff=True,
            first_name="Center",
            last_name="Admin",
        )

        self.teacher_1 = User.objects.create_user(
            username="teacher1",
            password="pass12345",
            role=User.Role.TEACHER,
            is_staff=True,
            first_name="Ali",
            last_name="Karimov",
        )
        self.teacher_2 = User.objects.create_user(
            username="teacher2",
            password="pass12345",
            role=User.Role.TEACHER,
            is_staff=True,
            first_name="Sara",
            last_name="Nabieva",
        )

        self.student_1 = User.objects.create_user(
            username="student1",
            password="pass12345",
            role=User.Role.STUDENT,
            first_name="Anvar",
            last_name="Saidov",
        )
        self.student_2 = User.objects.create_user(
            username="student2",
            password="pass12345",
            role=User.Role.STUDENT,
            first_name="Malika",
            last_name="Umarova",
        )

        self.subject_russian = Subject.objects.create(name="Русский")
        self.subject_english = Subject.objects.create(name="Английский")

        self.group_rus = StudyGroup.objects.create(
            subject=self.subject_russian,
            name="RUS-A1",
            level="A1",
            teacher=self.teacher_1,
            cycle_price=Decimal("1000.00"),
        )
        self.group_eng = StudyGroup.objects.create(
            subject=self.subject_english,
            name="ENG-B1",
            level="B1",
            teacher=self.teacher_2,
            cycle_price=Decimal("1500.00"),
        )

        GroupEnrollment.objects.create(group=self.group_rus, student=self.student_1)
        GroupEnrollment.objects.create(group=self.group_rus, student=self.student_2)
        GroupEnrollment.objects.create(group=self.group_eng, student=self.student_2)

    def _create_lessons(self, group: StudyGroup, count: int, start_delta_days: int = 0):
        base_dt = timezone.now() - timedelta(days=(count + start_delta_days))
        for idx in range(count):
            Lesson.objects.create(
                group=group,
                topic=f"Lesson {idx + 1}",
                starts_at=base_dt + timedelta(days=idx),
                homework="HW",
            )

    def test_teacher_performance_report_filters_by_subject(self):
        self._create_lessons(self.group_rus, 4)
        self._create_lessons(self.group_eng, 2)

        start = timezone.localdate() - timedelta(days=30)
        end = timezone.localdate() + timedelta(days=1)

        rows = teacher_performance_report(start, end)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].lessons_count, 4)

        rus_rows = teacher_performance_report(start, end, subject_id=self.subject_russian.id)
        self.assertEqual(len(rus_rows), 1)
        self.assertEqual(rus_rows[0].teacher_id, self.teacher_1.id)
        self.assertEqual(rus_rows[0].lessons_count, 4)

    def test_finance_summary_for_subject_and_whole_center(self):
        self._create_lessons(self.group_rus, 12)
        self._create_lessons(self.group_eng, 12)

        rus_cycle = BillingCycle.objects.get(group=self.group_rus, number=1)
        eng_cycle = BillingCycle.objects.get(group=self.group_eng, number=1)

        rus_payments = Payment.objects.filter(cycle=rus_cycle).order_by("student_id")
        eng_payments = Payment.objects.filter(cycle=eng_cycle).order_by("student_id")

        # Русский: 1 оплачено полностью, 1 частично
        payment_rus_paid = rus_payments[0]
        payment_rus_paid.amount_paid = Decimal("1000.00")
        payment_rus_paid.save()

        payment_rus_partial = rus_payments[1]
        payment_rus_partial.amount_paid = Decimal("300.00")
        payment_rus_partial.save()

        # Английский: полностью не оплачено
        payment_eng = eng_payments[0]
        payment_eng.amount_paid = Decimal("0.00")
        payment_eng.save()

        start = timezone.localdate() - timedelta(days=30)
        end = timezone.localdate() + timedelta(days=1)

        rus_summary = cycle_finance_report(start, end, subject_id=self.subject_russian.id)
        self.assertEqual(rus_summary.total_due, Decimal("2000.00"))
        self.assertEqual(rus_summary.total_paid, Decimal("1300.00"))
        self.assertEqual(rus_summary.total_partial_paid, Decimal("300.00"))
        self.assertEqual(rus_summary.total_debt, Decimal("700.00"))
        self.assertEqual(len(rus_summary.debtors), 1)

        center_summary = cycle_finance_report(start, end)
        self.assertEqual(center_summary.total_due, Decimal("3500.00"))
        self.assertEqual(center_summary.total_paid, Decimal("1300.00"))
        self.assertEqual(center_summary.total_debt, Decimal("2200.00"))
        self.assertEqual(len(center_summary.subject_breakdown), 2)

    def test_payment_statuses(self):
        self._create_lessons(self.group_rus, 12)
        cycle = BillingCycle.objects.get(group=self.group_rus, number=1)
        payment = Payment.objects.filter(cycle=cycle).first()

        self.assertEqual(payment.status, Payment.Status.UNPAID)
        payment.amount_paid = Decimal("500.00")
        payment.save()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PARTIAL)

        payment.amount_paid = Decimal("1000.00")
        payment.save()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)

    def test_super_admin_views_permissions(self):
        self._create_lessons(self.group_rus, 1)
        client = Client()

        # Center admin cannot access super-admin analytics.
        client.login(username="admin", password="pass12345")
        response = client.get(reverse("admin:crm_teacher_performance"))
        self.assertEqual(response.status_code, 403)

        # Super admin can access.
        client.login(username="super", password="pass12345")
        response = client.get(reverse("admin:crm_teacher_performance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Статистика учителей")

        response = client.get(reverse("admin:crm_cycle_finance_summary"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Финансы по циклам")

    def test_admin_can_create_user_without_server_error(self):
        client = Client()
        client.login(username="super", password="pass12345")
        response = client.post(
            "/admin/crm/user/add/",
            data={
                "username": "new_user_for_add_test",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "role": User.Role.STUDENT,
                "_save": "Save",
                "test_attempts-TOTAL_FORMS": "0",
                "test_attempts-INITIAL_FORMS": "0",
                "test_attempts-MIN_NUM_FORMS": "0",
                "test_attempts-MAX_NUM_FORMS": "1000",
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="new_user_for_add_test")
        self.assertFalse(created.is_active)
        self.assertFalse(created.is_active_in_center)

    def test_student_change_page_renders_without_500(self):
        client = Client()
        client.login(username="super", password="pass12345")

        student = User.objects.create_user(
            username="student_profile_page",
            password="pass12345",
            role=User.Role.STUDENT,
            is_staff=True,
            first_name="Profile",
            last_name="Student",
        )
        GroupEnrollment.objects.create(group=self.group_rus, student=student)

        response = client.get(f"/admin/crm/user/{student.pk}/change/")
        self.assertEqual(response.status_code, 200)

    def test_user_pdf_export_returns_file_with_photo(self):
        client = Client()
        client.login(username="super", password="pass12345")

        # 1x1 transparent PNG.
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
            b"\x00\x04\x00\x01\x0b\xe7\x02\x9d\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        student = User.objects.create_user(
            username="student_with_photo_pdf",
            password="pass12345",
            role=User.Role.STUDENT,
            is_staff=True,
            first_name="Тест",
            last_name="Студент",
            photo=SimpleUploadedFile("avatar.png", png_bytes, content_type="image/png"),
        )

        response = client.get(reverse("admin:crm_user_export_pdf", args=[student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))


class SeedDataCommandTests(TestCase):
    def test_seed_command_creates_demo_entities(self):
        call_command("seed_test_data")

        self.assertTrue(User.objects.filter(username="superadmin", role=User.Role.SUPER_ADMIN).exists())
        self.assertTrue(User.objects.filter(username="centeradmin", role=User.Role.CENTER_ADMIN).exists())
        self.assertEqual(Subject.objects.count(), 4)
        self.assertGreaterEqual(StudyGroup.objects.count(), 4)
        self.assertGreaterEqual(Lesson.objects.count(), 56)
        self.assertGreaterEqual(Payment.objects.count(), 12)
        self.assertTrue(Payment.objects.filter(status=Payment.Status.PARTIAL).exists())
        self.assertTrue(User.objects.filter(is_active_in_center=False).exists())


class PlacementSyncTests(TestCase):
    def test_final_test_attempt_updates_user_level_and_score(self):
        student = User.objects.create_user(
            username="placement_student",
            password="pass12345",
            role=User.Role.STUDENT,
            is_active=False,
            is_active_in_center=False,
            is_staff=True,
        )
        test = PlacementTest.objects.create(
            title="Student Placement",
            target_role=User.Role.STUDENT,
            question_count=100,
            is_active=True,
        )

        TestAttempt.objects.create(
            user=student,
            test=test,
            total_questions=100,
            correct_answers=81,
            is_final=True,
        )

        student.refresh_from_db()
        self.assertEqual(student.placement_level, User.PlacementLevel.ADVANCED)
        self.assertEqual(str(student.placement_score_percent), "81.00")
        self.assertTrue(student.is_active)
        self.assertTrue(student.is_active_in_center)
