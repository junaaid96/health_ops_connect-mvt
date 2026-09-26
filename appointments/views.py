from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from clinic.forms import ReviewForm
from clinic.models import Doctor
from clinic.triage import analyze
from core.utils import redirect_back
from core.permissions import patient_required

from . import services
from .forms import CancelForm, IntakeForm
from .models import Appointment


def get_appointment_for(user, code):
    """Fetch an appointment the user is allowed to see: their own, their
    patient's (doctor), or any (operations staff)."""
    appt = get_object_or_404(
        Appointment.objects.select_related("doctor__user", "doctor__specialty", "patient"), code=code
    )
    if appt.patient_id == user.pk or user.is_ops or (user.is_doctor and appt.doctor_id == user.doctor.pk):
        return appt
    raise Http404


def _parse_start(value):
    try:
        # A "+" in an unencoded query string arrives as a space.
        dt = datetime.fromisoformat(value.strip().replace(" ", "+"))
    except (AttributeError, TypeError, ValueError):
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


@patient_required
def book(request, slug):
    doctor = get_object_or_404(Doctor.objects.listed().select_related("user", "specialty"), slug=slug)
    start = _parse_start(request.GET.get("start") or request.POST.get("start"))
    if start is None:
        messages.error(request, "Pick a time slot first.")
        return redirect(doctor.get_absolute_url())
    initial_mode = request.GET.get("mode")
    form = IntakeForm(request.POST or None, doctor=doctor,
                      initial={"mode": initial_mode} if initial_mode else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            appt = services.book(
                request.user, doctor, start, data["mode"], data["reason"], data["symptoms"],
                data["severity"], data["symptom_duration"],
            )
        except services.BookingError as exc:
            messages.error(request, str(exc))
            return redirect(doctor.get_absolute_url() + f"?date={timezone.localtime(start).date().isoformat()}")
        return redirect(appt.get_absolute_url() + "?booked=1")
    ctx = {
        "doctor": doctor,
        "start": start,
        "form": form,
        "slot_minutes": next(
            (s.minutes for s in services.slots_for_day(doctor, timezone.localtime(start).date()) if s.start == start),
            doctor.default_slot_minutes,
        ),
    }
    return render(request, "appointments/book.html", ctx)


def triage_preview(request):
    """htmx partial: live hints while the patient types their intake."""
    text = f"{request.GET.get('reason', '')} {request.GET.get('symptoms', '')}".strip()
    result = analyze(text, severity=request.GET.get("severity"), duration=request.GET.get("symptom_duration"))
    return render(request, "appointments/_triage_hint.html", {"result": result, "text": text})


@login_required
def appointment_list(request):
    user = request.user
    if user.is_doctor:
        qs = Appointment.objects.filter(doctor=user.doctor).select_related("patient", "doctor__user")
    elif user.is_ops:
        return redirect("operations:front_desk")
    else:
        qs = Appointment.objects.filter(patient=user).select_related("doctor__user", "doctor__specialty")
    tab = request.GET.get("tab", "upcoming")
    items = qs.upcoming() if tab == "upcoming" else qs.past()
    page = Paginator(items, 15).get_page(request.GET.get("page"))
    return render(request, "appointments/list.html", {"page": page, "tab": tab})


@login_required
def detail(request, code):
    appt = get_appointment_for(request.user, code)
    if request.user.is_doctor and appt.doctor.user == request.user:
        return redirect("records:consult", code=appt.code)
    queue = services.queue_for(appt.doctor, appt.local_date) if appt.status == Appointment.Status.CHECKED_IN else None
    ctx = {
        "appt": appt,
        "queue_entry": queue.position_of(appt) if queue else None,
        "queue": queue,
        "consultation": getattr(appt, "consultation", None),
        "review_form": ReviewForm() if appt.status == Appointment.Status.COMPLETED and not hasattr(appt, "review") else None,
        "cancel_form": CancelForm(),
        "just_booked": request.GET.get("booked") == "1",
        "now": timezone.now(),
    }
    return render(request, "appointments/detail.html", ctx)


@login_required
def live_status(request, code):
    """htmx partial polled by the appointment page: queue position + ETA."""
    appt = get_appointment_for(request.user, code)
    queue = services.queue_for(appt.doctor, appt.local_date) if appt.status == Appointment.Status.CHECKED_IN else None
    return render(request, "appointments/_live_status.html", {
        "appt": appt, "queue": queue, "queue_entry": queue.position_of(appt) if queue else None,
        "now": timezone.now(),
    })


@login_required
@require_POST
def cancel(request, code):
    appt = get_appointment_for(request.user, code)
    form = CancelForm(request.POST)
    reason = form.cleaned_data["reason"] if form.is_valid() else ""
    try:
        services.cancel(appt, request.user, reason)
        messages.success(request, "Appointment cancelled. The slot has been released to others.")
    except services.BookingError as exc:
        messages.error(request, str(exc))
    return redirect_back(request, appt.get_absolute_url())


@login_required
@require_POST
def check_in(request, code):
    appt = get_appointment_for(request.user, code)
    try:
        services.check_in(appt)
        messages.success(request, f"You're checked in. Your token is #{appt.token}.")
    except services.BookingError as exc:
        messages.error(request, str(exc))
    return redirect_back(request, appt.get_absolute_url())


@patient_required
def reschedule(request, code):
    appt = get_object_or_404(Appointment.objects.select_related("doctor__user"), code=code, patient=request.user)
    if not appt.can_reschedule():
        messages.error(request, "This appointment can no longer be rescheduled.")
        return redirect(appt.get_absolute_url())
    if request.method == "POST":
        start = _parse_start(request.POST.get("start"))
        try:
            if start is None:
                raise services.BookingError("Pick a new time slot.")
            services.reschedule(appt, start, request.user)
            messages.success(request, "Appointment rescheduled.")
            return redirect(appt.get_absolute_url())
        except services.BookingError as exc:
            messages.error(request, str(exc))
    calendar = services.calendar_for(appt.doctor, exclude_pk=appt.pk)
    day = next((d for d, n, _ in calendar if n), calendar[0][0])
    return render(request, "appointments/reschedule.html", {
        "appt": appt, "doctor": appt.doctor, "calendar": calendar, "day": day,
        "slots": services.slots_for_day(appt.doctor, day, exclude_pk=appt.pk), "reschedule": appt,
    })


def _ics_escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@login_required
def ics(request, code):
    appt = get_appointment_for(request.user, code)

    def stamp(dt):
        return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    location = appt.video_url if appt.mode == Appointment.Mode.VIDEO else (appt.doctor.room or settings.SITE_NAME)
    description = f"Appointment {appt.code} with {appt.doctor} ({appt.doctor.specialty}).\\n" \
                  f"Manage: {settings.SITE_URL}{appt.get_absolute_url()}"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HealthOPS Connect//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{appt.code}@healthops-connect",
        f"DTSTAMP:{stamp(timezone.now())}",
        f"DTSTART:{stamp(appt.scheduled_at)}",
        f"DTEND:{stamp(appt.ends_at)}",
        f"SUMMARY:{_ics_escape(f'{appt.get_mode_display()} with {appt.doctor}')}",
        f"LOCATION:{_ics_escape(location)}",
        f"DESCRIPTION:{description}",
        "BEGIN:VALARM", "TRIGGER:-PT1H", "ACTION:DISPLAY", "DESCRIPTION:Appointment reminder", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    response = HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{appt.code}.ics"'
    return response


@login_required
def join_video(request, code):
    appt = get_appointment_for(request.user, code)
    if not appt.can_join_video():
        messages.info(request, "The video room opens 15 minutes before your appointment.")
        return redirect(appt.get_absolute_url())
    return redirect(appt.video_url)
