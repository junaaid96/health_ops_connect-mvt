import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_code(prefix="HOC", length=6):
    return f"{prefix}-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


class Urgency(models.IntegerChoices):
    ROUTINE = 1, "Routine"
    SOON = 2, "Needs attention soon"
    URGENT = 3, "Urgent"


class AppointmentQuerySet(models.QuerySet):
    def active(self):
        return self.exclude(status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW])

    def upcoming(self):
        """Booked visits that haven't long passed, plus anyone checked in or
        with the doctor today (they're still in the building)."""
        today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.filter(
            Q(status=Appointment.Status.BOOKED, scheduled_at__gte=timezone.now() - timedelta(hours=3))
            | Q(status__in=[Appointment.Status.CHECKED_IN, Appointment.Status.IN_PROGRESS],
                scheduled_at__gte=today_start)
        ).order_by("scheduled_at")

    def past(self):
        return self.exclude(pk__in=self.upcoming().values("pk")).order_by("-scheduled_at")

    def on_date(self, date):
        return self.filter(scheduled_at__date=date)


class Appointment(models.Model):
    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        CHECKED_IN = "checked_in", "Checked in"
        IN_PROGRESS = "in_progress", "In consultation"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No-show"

    class Mode(models.TextChoices):
        IN_PERSON = "in_person", "In person"
        VIDEO = "video", "Video visit"

    class Payment(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        WAIVED = "waived", "Waived"

    class SymptomDuration(models.TextChoices):
        HOURS = "hours", "A few hours"
        DAYS = "days", "A few days"
        WEEKS = "weeks", "A few weeks"
        MONTHS = "months", "Months or longer"

    code = models.CharField(max_length=12, unique=True, editable=False)
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="appointments")
    doctor = models.ForeignKey("clinic.Doctor", on_delete=models.CASCADE, related_name="appointments")
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=20)
    mode = models.CharField(max_length=12, choices=Mode.choices, default=Mode.IN_PERSON)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.BOOKED, db_index=True)

    # Digital intake, completed by the patient while booking.
    reason = models.CharField("Main reason for visit", max_length=200)
    symptoms = models.TextField(blank=True)
    severity = models.PositiveSmallIntegerField(default=3, help_text="Self-reported, 1–10")
    symptom_duration = models.CharField(max_length=10, choices=SymptomDuration.choices, default=SymptomDuration.DAYS)
    urgency = models.PositiveSmallIntegerField(choices=Urgency.choices, default=Urgency.ROUTINE)
    red_flags = models.CharField(max_length=300, blank=True)

    # Billing snapshot.
    fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=8, choices=Payment.choices, default=Payment.UNPAID)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Queue & lifecycle timestamps.
    queue_number = models.PositiveIntegerField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reminder_sent = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AppointmentQuerySet.as_manager()

    class Meta:
        ordering = ["scheduled_at"]
        constraints = [
            # The database, not the view, guarantees a slot can't be double-booked.
            models.UniqueConstraint(
                fields=["doctor", "scheduled_at"],
                condition=~Q(status__in=["cancelled"]),
                name="uniq_active_booking_per_slot",
            ),
        ]
        indexes = [
            models.Index(fields=["doctor", "scheduled_at"]),
            models.Index(fields=["patient", "scheduled_at"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self):
        return f"{self.code} · {self.patient} with {self.doctor}"

    def save(self, *args, **kwargs):
        if not self.code:
            code = generate_code()
            while Appointment.objects.filter(code=code).exists():
                code = generate_code()
            self.code = code
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("appointments:detail", args=[self.code])

    # --- derived ----------------------------------------------------------
    @property
    def ends_at(self):
        return self.scheduled_at + timedelta(minutes=self.duration_minutes)

    @property
    def local_date(self):
        return timezone.localtime(self.scheduled_at).date()

    @property
    def is_open(self):
        return self.status in (self.Status.BOOKED, self.Status.CHECKED_IN, self.Status.IN_PROGRESS)

    @property
    def token(self):
        return f"{self.queue_number:03d}" if self.queue_number else "—"

    @property
    def video_url(self):
        if self.mode != self.Mode.VIDEO:
            return ""
        if self.doctor.video_link:
            return self.doctor.video_link
        # Unguessable per-visit room name derived from the secret key.
        digest = hashlib.sha256(f"{settings.SECRET_KEY}:{self.code}".encode()).hexdigest()[:10]
        return f"{settings.VIDEO_BASE_URL}/HealthOPS-{self.code}-{digest}"

    def can_join_video(self, now=None):
        now = now or timezone.now()
        return (
            self.mode == self.Mode.VIDEO
            and self.is_open
            and self.scheduled_at - timedelta(minutes=15) <= now <= self.ends_at + timedelta(minutes=30)
        )

    def can_check_in(self, now=None):
        now = now or timezone.now()
        opens = self.scheduled_at - timedelta(minutes=settings.CHECKIN_OPENS_MINUTES)
        return self.status == self.Status.BOOKED and opens <= now <= self.ends_at

    def can_cancel(self, now=None):
        now = now or timezone.now()
        return self.status in (self.Status.BOOKED, self.Status.CHECKED_IN) and now < self.ends_at

    def can_reschedule(self, now=None):
        now = now or timezone.now()
        return self.status == self.Status.BOOKED and now < self.scheduled_at


class WaitlistEntry(models.Model):
    """A patient who wants a slot with a doctor on a fully booked day.
    They get notified as soon as someone cancels."""

    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waitlist")
    doctor = models.ForeignKey("clinic.Doctor", on_delete=models.CASCADE, related_name="waitlist")
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["patient", "doctor", "date"], name="uniq_waitlist_entry"),
        ]
        verbose_name_plural = "waitlist entries"

    def __str__(self):
        return f"{self.patient} waiting for {self.doctor} on {self.date}"
