"""Scheduling, check-in and queue logic.

Views stay thin; every state change on an appointment goes through here so
the rules (and notifications) live in one place.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from clinic.models import Doctor
from clinic.triage import analyze
from core.notify import notify

from .models import Appointment, WaitlistEntry

Status = Appointment.Status


class BookingError(Exception):
    pass


@dataclass(frozen=True)
class Slot:
    start: datetime
    minutes: int
    status: str  # "open" | "booked" | "past"

    @property
    def is_open(self):
        return self.status == "open"

    @property
    def iso(self):
        return timezone.localtime(self.start).isoformat()


def _aware(day, t):
    return timezone.make_aware(datetime.combine(day, t), timezone.get_current_timezone())


def local_today():
    return timezone.localdate()


def booking_days(start=None, days=None):
    start = start or local_today()
    return [start + timedelta(days=i) for i in range(days or settings.BOOKING_WINDOW_DAYS)]


def _generate(blocks, day):
    for block in blocks:
        if block.weekday != day.weekday():
            continue
        step = timedelta(minutes=block.slot_minutes)
        cursor = _aware(day, block.start_time)
        end = _aware(day, block.end_time)
        while cursor + step <= end:
            yield cursor, block.slot_minutes
            cursor += step


def _day_slots(blocks, day, booked, off_days, now):
    if day in off_days:
        return []
    slots = []
    for start, minutes in _generate(blocks, day):
        if start in booked:
            status = "booked"
        elif start <= now:
            status = "past"
        else:
            status = "open"
        slots.append(Slot(start, minutes, status))
    return slots


def _booked_starts(doctor_ids, start_day, end_day, exclude_pk=None):
    qs = Appointment.objects.filter(
        doctor_id__in=doctor_ids,
        scheduled_at__gte=_aware(start_day, datetime.min.time()),
        scheduled_at__lt=_aware(end_day + timedelta(days=1), datetime.min.time()),
    ).exclude(status=Status.CANCELLED)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    booked = defaultdict(set)
    for doctor_id, start in qs.values_list("doctor_id", "scheduled_at"):
        booked[doctor_id].add(start)
    return booked


def slots_for_day(doctor, day, now=None, exclude_pk=None):
    now = now or timezone.now()
    blocks = list(doctor.availability.all())
    off = set(doctor.time_off.filter(date=day).values_list("date", flat=True))
    booked = _booked_starts([doctor.pk], day, day, exclude_pk)[doctor.pk]
    return _day_slots(blocks, day, booked, off, now)


def calendar_for(doctor, days=None, now=None, exclude_pk=None):
    """[(date, open_slot_count, total_slot_count)] for the booking strip."""
    now = now or timezone.now()
    days = days or booking_days()
    blocks = list(doctor.availability.all())
    off = set(doctor.time_off.filter(date__range=(days[0], days[-1])).values_list("date", flat=True))
    booked = _booked_starts([doctor.pk], days[0], days[-1], exclude_pk)[doctor.pk]
    out = []
    for day in days:
        slots = _day_slots(blocks, day, booked, off, now)
        out.append((day, sum(s.is_open for s in slots), len(slots)))
    return out


def next_available(doctors, days=None, now=None):
    """{doctor_id: first open slot datetime or None}, computed with a fixed
    number of queries regardless of how many doctors are listed."""
    now = now or timezone.now()
    doctors = list(doctors)
    if not doctors:
        return {}
    days = days or booking_days()
    ids = [d.pk for d in doctors]
    booked = _booked_starts(ids, days[0], days[-1])
    from clinic.models import TimeOff, WeeklyAvailability

    blocks = defaultdict(list)
    for block in WeeklyAvailability.objects.filter(doctor_id__in=ids):
        blocks[block.doctor_id].append(block)
    off = defaultdict(set)
    for doctor_id, day in TimeOff.objects.filter(doctor_id__in=ids, date__range=(days[0], days[-1])).values_list(
        "doctor_id", "date"
    ):
        off[doctor_id].add(day)
    result = {}
    for doctor in doctors:
        result[doctor.pk] = None
        for day in days:
            slot = next(
                (s for s in _day_slots(blocks[doctor.pk], day, booked[doctor.pk], off[doctor.pk], now) if s.is_open),
                None,
            )
            if slot:
                result[doctor.pk] = slot.start
                break
    return result


def _validate_slot(doctor, start, now, exclude_pk=None):
    day = timezone.localtime(start).date()
    if day not in booking_days():
        raise BookingError(f"Appointments can be booked up to {settings.BOOKING_WINDOW_DAYS} days ahead.")
    slot = next((s for s in slots_for_day(doctor, day, now, exclude_pk) if s.start == start), None)
    if slot is None:
        raise BookingError("That time isn't part of the doctor's schedule.")
    if slot.status == "past":
        raise BookingError("That time has already passed.")
    if slot.status == "booked":
        raise BookingError("Sorry — that slot was just taken. Please pick another time.")
    return slot


def _patient_clash(patient, start, minutes, exclude_pk=None):
    end = start + timedelta(minutes=minutes)
    qs = patient.appointments.filter(
        status__in=[Status.BOOKED, Status.CHECKED_IN, Status.IN_PROGRESS],
        scheduled_at__lt=end,
        scheduled_at__gt=start - timedelta(hours=2),
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return next((a for a in qs.select_related("doctor__user") if a.ends_at > start), None)


def book(patient, doctor, start, mode, reason, symptoms="", severity=3, symptom_duration="days", now=None):
    now = now or timezone.now()
    if not patient.is_patient:
        raise BookingError("Only patient accounts can book appointments.")
    if not doctor.is_verified:
        raise BookingError("This doctor isn't accepting bookings yet.")
    if mode == Appointment.Mode.VIDEO and not doctor.offers_video:
        raise BookingError("This doctor doesn't offer video visits.")
    if mode == Appointment.Mode.IN_PERSON and not doctor.offers_in_person:
        raise BookingError("This doctor only offers video visits.")
    slot = _validate_slot(doctor, start, now)
    clash = _patient_clash(patient, start, slot.minutes)
    if clash:
        raise BookingError(f"You already have an appointment with {clash.doctor} at that time.")

    triage = analyze(f"{reason} {symptoms}", severity=severity, duration=symptom_duration)
    try:
        with transaction.atomic():
            appt = Appointment.objects.create(
                patient=patient,
                doctor=doctor,
                scheduled_at=start,
                duration_minutes=slot.minutes,
                mode=mode,
                reason=reason,
                symptoms=symptoms,
                severity=severity,
                symptom_duration=symptom_duration,
                urgency=triage.urgency,
                red_flags="; ".join(f["phrase"] for f in triage.red_flags),
                fee=doctor.fee,
            )
    except IntegrityError:
        raise BookingError("Sorry — that slot was just taken. Please pick another time.")

    WaitlistEntry.objects.filter(patient=patient, doctor=doctor, date=appt.local_date).delete()
    when = _fmt(appt.scheduled_at)
    notify(patient, "Appointment confirmed", f"{doctor} · {when} · {appt.get_mode_display()}",
           appt.get_absolute_url(), kind="success", email=True)
    notify(doctor.user, "New booking", f"{patient.display_name} · {when} · {appt.reason}",
           reverse("core:dashboard"), kind="alert" if triage.urgency == 3 else "info")
    return appt


def reschedule(appt, new_start, by, now=None):
    now = now or timezone.now()
    if not appt.can_reschedule(now):
        raise BookingError("This appointment can no longer be rescheduled.")
    slot = _validate_slot(appt.doctor, new_start, now, exclude_pk=appt.pk)
    clash = _patient_clash(appt.patient, new_start, slot.minutes, exclude_pk=appt.pk)
    if clash:
        raise BookingError(f"You already have an appointment with {clash.doctor} at that time.")
    old_start = appt.scheduled_at
    try:
        with transaction.atomic():
            appt.scheduled_at = new_start
            appt.duration_minutes = slot.minutes
            appt.reminder_sent = False
            appt.save(update_fields=["scheduled_at", "duration_minutes", "reminder_sent", "updated_at"])
    except IntegrityError:
        appt.scheduled_at = old_start
        raise BookingError("Sorry — that slot was just taken. Please pick another time.")
    msg = f"Moved from {_fmt(old_start)} to {_fmt(new_start)}"
    notify(appt.patient, "Appointment rescheduled", msg, appt.get_absolute_url(), kind="info", email=True)
    notify(appt.doctor.user, "Appointment rescheduled", f"{appt.patient.display_name}: {msg}",
           reverse("core:dashboard"))
    _notify_waitlist(appt.doctor, timezone.localtime(old_start).date())
    return appt


def cancel(appt, by, reason="", now=None):
    now = now or timezone.now()
    if not appt.can_cancel(now):
        raise BookingError("This appointment can't be cancelled.")
    appt.status = Status.CANCELLED
    appt.cancelled_at = now
    appt.cancelled_by = by
    appt.cancel_reason = reason[:200]
    appt.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancel_reason", "updated_at"])
    when = _fmt(appt.scheduled_at)
    if by == appt.patient:
        notify(appt.doctor.user, "Appointment cancelled", f"{appt.patient.display_name} cancelled {when}",
               reverse("core:dashboard"))
    else:
        notify(appt.patient, "Your appointment was cancelled",
               f"{appt.doctor} · {when}" + (f" — {reason}" if reason else ""),
               appt.get_absolute_url(), kind="warning", email=True)
    _notify_waitlist(appt.doctor, appt.local_date)
    return appt


def _notify_waitlist(doctor, day):
    if day < local_today():
        return
    entries = WaitlistEntry.objects.filter(doctor=doctor, date=day, notified_at__isnull=True).select_related("patient")
    url = doctor.get_absolute_url() + f"?date={day.isoformat()}"
    for entry in entries:
        notify(entry.patient, "A slot just opened up",
               f"{doctor} has a free slot on {day:%a %d %b}. Book it before someone else does!",
               url, kind="success", email=True)
    entries.update(notified_at=timezone.now())


def join_waitlist(patient, doctor, day):
    if day not in booking_days():
        raise BookingError("You can only join the waitlist for days in the booking window.")
    entry, created = WaitlistEntry.objects.get_or_create(patient=patient, doctor=doctor, date=day)
    return entry, created


# --- Day-of-visit flow ------------------------------------------------------

@transaction.atomic
def check_in(appt, now=None):
    now = now or timezone.now()
    if not appt.can_check_in(now):
        if appt.status != Status.BOOKED:
            raise BookingError("This appointment is already checked in or closed.")
        raise BookingError(
            f"Check-in opens {settings.CHECKIN_OPENS_MINUTES} minutes before your appointment and closes when it ends."
        )
    # Lock the doctor row so two simultaneous check-ins can't get the same token.
    Doctor.objects.select_for_update().get(pk=appt.doctor_id)
    last = (
        Appointment.objects.filter(doctor_id=appt.doctor_id)
        .on_date(appt.local_date)
        .aggregate(m=Max("queue_number"))["m"]
    )
    appt.queue_number = (last or 0) + 1
    appt.status = Status.CHECKED_IN
    appt.checked_in_at = now
    appt.save(update_fields=["queue_number", "status", "checked_in_at", "updated_at"])
    return appt


@dataclass
class QueueEntry:
    appointment: Appointment
    position: int
    eta: datetime
    wait_minutes: int


@dataclass
class QueueState:
    current: Appointment | None
    waiting: list
    avg_minutes: int

    def position_of(self, appt):
        return next((e for e in self.waiting if e.appointment.pk == appt.pk), None)


def _avg_minutes_map(doctors):
    """Per-doctor average consultation length, learned from their recent real
    visits (falls back to slot length). Keeps wait estimates honest."""
    ids = [d.pk for d in doctors]
    rows = (
        Appointment.objects.filter(doctor_id__in=ids, status=Status.COMPLETED,
                                   started_at__isnull=False, completed_at__isnull=False,
                                   completed_at__gte=timezone.now() - timedelta(days=60))
        .order_by("-completed_at")
        .values_list("doctor_id", "started_at", "completed_at")
    )
    durations = defaultdict(list)
    for doctor_id, start, end in rows:
        if end > start and len(durations[doctor_id]) < 20:
            durations[doctor_id].append((end - start).total_seconds() / 60)
    out = {}
    for doctor in doctors:
        values = durations[doctor.pk]
        if len(values) >= 3:
            out[doctor.pk] = max(5, min(60, round(sum(values) / len(values))))
        else:
            out[doctor.pk] = doctor.default_slot_minutes
    return out


def average_consult_minutes(doctor):
    return _avg_minutes_map([doctor])[doctor.pk]


def queues_for(doctors, day=None, now=None):
    """{doctor_id: QueueState} for several doctors with a constant number of
    queries. Waiting patients are ordered by triage urgency, then arrival."""
    now = now or timezone.now()
    day = day or local_today()
    doctors = list(doctors)
    active = (
        Appointment.objects.filter(doctor_id__in=[d.pk for d in doctors],
                                   status__in=[Status.CHECKED_IN, Status.IN_PROGRESS])
        .on_date(day)
        .select_related("patient", "patient__health", "doctor__user")
    )
    by_doctor = defaultdict(list)
    for appt in active:
        by_doctor[appt.doctor_id].append(appt)
    avgs = _avg_minutes_map(doctors)
    states = {}
    for doctor in doctors:
        appts = by_doctor[doctor.pk]
        in_progress = sorted((a for a in appts if a.status == Status.IN_PROGRESS), key=lambda a: a.started_at or now)
        current = in_progress[0] if in_progress else None
        waiting = sorted((a for a in appts if a.status == Status.CHECKED_IN),
                         key=lambda a: (-a.urgency, a.checked_in_at or now))
        avg = avgs[doctor.pk]
        remaining_current = 0
        if current and current.started_at:
            elapsed = (now - current.started_at).total_seconds() / 60
            remaining_current = max(2, avg - elapsed)
        entries = []
        for i, appt in enumerate(waiting):
            wait = round(remaining_current + i * avg)
            entries.append(QueueEntry(appt, i + 1, now + timedelta(minutes=wait), wait))
        states[doctor.pk] = QueueState(current, entries, avg)
    return states


def queue_for(doctor, day=None, now=None):
    return queues_for([doctor], day, now)[doctor.pk]


def slots_for_doctors(doctors, day, now=None):
    """{doctor_id: [Slot]} for one day across many doctors (availability
    should be prefetched)."""
    now = now or timezone.now()
    doctors = list(doctors)
    ids = [d.pk for d in doctors]
    booked = _booked_starts(ids, day, day)
    from clinic.models import TimeOff

    off = set(TimeOff.objects.filter(doctor_id__in=ids, date=day).values_list("doctor_id", flat=True))
    return {
        d.pk: ([] if d.pk in off else _day_slots(list(d.availability.all()), day, booked[d.pk], set(), now))
        for d in doctors
    }


@transaction.atomic
def start_consultation(appt, now=None):
    now = now or timezone.now()
    if appt.status not in (Status.BOOKED, Status.CHECKED_IN):
        raise BookingError("This appointment can't be started.")
    if appt.local_date != local_today():
        raise BookingError("Only today's appointments can be started.")
    busy = Appointment.objects.filter(doctor=appt.doctor, status=Status.IN_PROGRESS).exclude(pk=appt.pk).first()
    if busy:
        raise BookingError(f"Finish the consultation with {busy.patient.display_name} first.")
    appt.status = Status.IN_PROGRESS
    appt.started_at = now
    appt.save(update_fields=["status", "started_at", "updated_at"])
    where = "Join the video call from your appointment page." if appt.mode == Appointment.Mode.VIDEO else (
        f"Please proceed to {appt.doctor.room}." if appt.doctor.room else "Please proceed to the consultation room."
    )
    notify(appt.patient, "It's your turn", f"{appt.doctor} is ready for you. {where}",
           appt.get_absolute_url(), kind="alert")
    return appt


def call_next(doctor, now=None):
    state = queue_for(doctor, now=now)
    if state.current:
        raise BookingError(f"Finish the consultation with {state.current.patient.display_name} first.")
    if not state.waiting:
        raise BookingError("Nobody is waiting right now.")
    return start_consultation(state.waiting[0].appointment, now=now)


def complete(appt, now=None):
    now = now or timezone.now()
    appt.status = Status.COMPLETED
    appt.completed_at = now
    appt.started_at = appt.started_at or now
    appt.save(update_fields=["status", "completed_at", "started_at", "updated_at"])
    notify(appt.patient, "Visit summary & prescription ready",
           f"Your consultation with {appt.doctor} is complete. You can view and print your prescription.",
           appt.get_absolute_url(), kind="success", email=True)
    return appt


def mark_no_show(appt, now=None):
    now = now or timezone.now()
    if appt.status not in (Status.BOOKED, Status.CHECKED_IN) or now < appt.scheduled_at:
        raise BookingError("Only appointments that have started without the patient can be marked as no-show.")
    appt.status = Status.NO_SHOW
    appt.save(update_fields=["status", "updated_at"])
    return appt


def mark_paid(appt, now=None):
    appt.payment_status = Appointment.Payment.PAID
    appt.paid_at = now or timezone.now()
    appt.save(update_fields=["payment_status", "paid_at", "updated_at"])
    return appt


def _fmt(dt):
    return timezone.localtime(dt).strftime("%a %d %b, %I:%M %p")
