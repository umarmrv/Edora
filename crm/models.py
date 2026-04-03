from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "SUPER_ADMIN", "Супер-админ"
        CENTER_ADMIN = "CENTER_ADMIN", "Администрация центра"
        TEACHER = "TEACHER", "Учитель"
        STUDENT = "STUDENT", "Студент"

    class SchoolShift(models.TextChoices):
        MORNING = "MORNING", "Утро"
        AFTERNOON = "AFTERNOON", "День"
        EVENING = "EVENING", "Вечер"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    middle_name = models.CharField(max_length=150, blank=True)
    phone_student = models.CharField(max_length=32, blank=True)
    phone_parent = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(upload_to="profiles/", blank=True, null=True)
    school_name = models.CharField(max_length=255, blank=True)
    school_shift = models.CharField(max_length=20, choices=SchoolShift.choices, blank=True)
    is_active_in_center = models.BooleanField(default=True)
    joined_center_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join([part for part in parts if part]).strip() or self.username


class Subject(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Предмет"
        verbose_name_plural = "Предметы"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class StudyGroup(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="groups")
    name = models.CharField(max_length=120)
    level = models.CharField(max_length=60)
    course_duration_weeks = models.PositiveIntegerField(default=12)
    cycle_price = models.DecimalField(max_digits=12, decimal_places=2)
    teacher = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teaching_groups",
        limit_choices_to={"role": User.Role.TEACHER},
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Группа"
        verbose_name_plural = "Группы"
        ordering = ["subject__name", "name"]
        unique_together = ["subject", "name"]

    def __str__(self) -> str:
        return f"{self.subject.name} / {self.name}"


class GroupSchedule(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 1, "Понедельник"
        TUESDAY = 2, "Вторник"
        WEDNESDAY = 3, "Среда"
        THURSDAY = 4, "Четверг"
        FRIDAY = 5, "Пятница"
        SATURDAY = 6, "Суббота"
        SUNDAY = 7, "Воскресенье"

    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name="schedules")
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        verbose_name = "Расписание группы"
        verbose_name_plural = "Расписания групп"
        ordering = ["group", "day_of_week", "start_time"]

    def __str__(self) -> str:
        return f"{self.group}: {self.get_day_of_week_display()} {self.start_time}-{self.end_time}"


class GroupEnrollment(models.Model):
    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="group_enrollments",
        limit_choices_to={"role": User.Role.STUDENT},
    )
    started_at = models.DateField(default=timezone.localdate)
    ended_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Зачисление в группу"
        verbose_name_plural = "Зачисления в группы"
        constraints = [
            models.UniqueConstraint(
                fields=["group", "student"],
                condition=Q(is_active=True),
                name="unique_active_enrollment",
            )
        ]

    def clean(self) -> None:
        if self.student.role != User.Role.STUDENT:
            raise ValidationError("В группу можно зачислять только пользователей с ролью Студент.")

    def __str__(self) -> str:
        return f"{self.student.full_name} -> {self.group}"


class Lesson(models.Model):
    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name="lessons")
    topic = models.CharField(max_length=255)
    starts_at = models.DateTimeField()
    homework = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Урок"
        verbose_name_plural = "Уроки"
        ordering = ["-starts_at"]

    def __str__(self) -> str:
        return f"{self.group} / {self.topic} ({self.starts_at:%Y-%m-%d})"


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Присутствует"
        ABSENT = "ABSENT", "Отсутствует"
        LATE = "LATE", "Опоздал"

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attendance_records")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendance_records")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PRESENT)
    comment = models.TextField(blank=True)
    activity_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
    homework_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
    exam_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    class Meta:
        verbose_name = "Посещаемость"
        verbose_name_plural = "Посещаемость"
        unique_together = ["lesson", "student"]

    def __str__(self) -> str:
        return f"{self.student.full_name} / {self.lesson}"


class BillingCycle(models.Model):
    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name="billing_cycles")
    number = models.PositiveIntegerField()
    opened_at = models.DateTimeField(auto_now_add=True)
    lesson_start_number = models.PositiveIntegerField(default=1)
    lesson_end_number = models.PositiveIntegerField(default=12)

    class Meta:
        verbose_name = "Платежный цикл"
        verbose_name_plural = "Платежные циклы"
        ordering = ["-opened_at"]
        unique_together = ["group", "number"]

    def __str__(self) -> str:
        return f"{self.group} / Цикл {self.number}"


class Payment(models.Model):
    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Не оплачено"
        PARTIAL = "PARTIAL", "Частично оплачено"
        PAID = "PAID", "Оплачено"

    cycle = models.ForeignKey(BillingCycle, on_delete=models.CASCADE, related_name="payments")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payments")
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNPAID)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Платеж"
        verbose_name_plural = "Платежи"
        ordering = ["-cycle__opened_at", "student__last_name"]
        unique_together = ["cycle", "student"]

    @property
    def amount_remaining(self) -> Decimal:
        remaining = self.amount_due - self.amount_paid
        return remaining if remaining > 0 else Decimal("0.00")

    def refresh_status(self) -> None:
        if self.amount_paid <= 0:
            self.status = self.Status.UNPAID
            self.paid_at = None
        elif self.amount_paid < self.amount_due:
            self.status = self.Status.PARTIAL
            self.paid_at = None
        else:
            self.status = self.Status.PAID
            if not self.paid_at:
                self.paid_at = timezone.now()

    def clean(self) -> None:
        if self.student.role != User.Role.STUDENT:
            raise ValidationError("Платежи можно создавать только для учеников.")
        if self.amount_paid < 0:
            raise ValidationError("Сумма оплаты не может быть отрицательной.")

    def save(self, *args, **kwargs):
        self.refresh_status()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.student.full_name} / {self.cycle}"


class UserExitRecord(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="exit_record")
    reason = models.TextField()
    exited_at = models.DateTimeField(auto_now_add=True)
    removed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="processed_exits",
        limit_choices_to={"role__in": [User.Role.CENTER_ADMIN, User.Role.SUPER_ADMIN]},
    )

    class Meta:
        verbose_name = "Выбытие пользователя"
        verbose_name_plural = "Выбытия пользователей"
        ordering = ["-exited_at"]

    def clean(self) -> None:
        if not self.reason.strip():
            raise ValidationError("Причина выбытия обязательна.")

    def __str__(self) -> str:
        return f"{self.user.full_name} / выбыл {self.exited_at:%Y-%m-%d}"


class PlacementTest(models.Model):
    class TargetRole(models.TextChoices):
        STUDENT = User.Role.STUDENT, "Тест для ученика"
        TEACHER = User.Role.TEACHER, "Тест для учителя"

    title = models.CharField(max_length=255)
    target_role = models.CharField(max_length=20, choices=TargetRole.choices)
    question_count = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Тест определения уровня"
        verbose_name_plural = "Тесты определения уровня"

    def clean(self) -> None:
        if self.question_count < 100:
            raise ValidationError("Количество вопросов в тесте должно быть не меньше 100.")

    def __str__(self) -> str:
        return self.title


class TestAttempt(models.Model):
    LEVEL_BEGINNER = "BEGINNER"
    LEVEL_BASIC = "BASIC"
    LEVEL_INTERMEDIATE = "INTERMEDIATE"
    LEVEL_ADVANCED = "ADVANCED"

    LEVEL_CHOICES = [
        (LEVEL_BEGINNER, "Начальный"),
        (LEVEL_BASIC, "Базовый"),
        (LEVEL_INTERMEDIATE, "Средний"),
        (LEVEL_ADVANCED, "Продвинутый"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="test_attempts")
    test = models.ForeignKey(PlacementTest, on_delete=models.CASCADE, related_name="attempts")
    total_questions = models.PositiveIntegerField(default=100)
    correct_answers = models.PositiveIntegerField(default=0)
    score_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, blank=True)
    taken_at = models.DateTimeField(auto_now_add=True)
    is_final = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Попытка тестирования"
        verbose_name_plural = "Попытки тестирования"
        ordering = ["-taken_at"]

    @staticmethod
    def detect_level(score_percent: Decimal) -> str:
        if score_percent < 40:
            return TestAttempt.LEVEL_BEGINNER
        if score_percent < 60:
            return TestAttempt.LEVEL_BASIC
        if score_percent < 80:
            return TestAttempt.LEVEL_INTERMEDIATE
        return TestAttempt.LEVEL_ADVANCED

    def clean(self) -> None:
        if self.total_questions < 100:
            raise ValidationError("Попытка теста должна содержать не менее 100 вопросов.")
        if self.correct_answers > self.total_questions:
            raise ValidationError("Число правильных ответов не может превышать общее число вопросов.")
        if self.user.role not in {User.Role.STUDENT, User.Role.TEACHER}:
            raise ValidationError("Тест доступен только для ролей ученик/учитель.")

    def save(self, *args, **kwargs):
        if self.total_questions:
            percent = (Decimal(self.correct_answers) / Decimal(self.total_questions)) * Decimal("100")
            self.score_percent = percent.quantize(Decimal("0.01"))
        self.level = self.detect_level(self.score_percent)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user.full_name} / {self.score_percent}%"
