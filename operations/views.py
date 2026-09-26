from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from appointments import services
from appointments.models import Appointment
from clinic.models import Doctor
from core.notify import notify
from core.permissions import ops_required
from core.utils import redirect_back
from records.models import AccessLog

from .forms import AdmissionForm
from .models import Admission, Bed, Ward

Status = Appointment.Status


def _doctor_load(today, now):
    rows = []
    doctors = list(Doctor.objects.listed().select_related("user", "specialty").prefetch_related("availability"))
    slot_map = services.slots_for_doctors(doctors, today, now=now)
    queues = services.queues_for(doctors, today, now=now)
    for doctor in doctors:
        slots = slot_map[doctor.pk]
        if not slots:
            continue
        booked = sum(1 for s in slots if s.status == "booked")
        queue = queues[doctor.pk]
        rows.append({
            "doctor": doctor,
            "booked": booked,
            "total": len(slots),
            "utilization": round(100 * booked / len(slots)),
            "waiting": len(queue.waiting),
            "current": queue.current,
            "avg": queue.avg_minutes,
        })
    rows.sort(key=lambda r: -r["utilization"])
    return rows


@ops_required
def dashboard(request):
    now = timezone.now()
    today = services.local_today()
    todays = Appointment.objects.on_date(today)
    counts = todays.aggregate(
        total=Count("id", filter=~Q(status=Status.CANCELLED)),
        waiting=Count("id", filter=Q(status=Status.CHECKED_IN)),
        in_progress=Count("id", filter=Q(status=Status.IN_PROGRESS)),
        completed=Count("id", filter=Q(status=Status.COMPLETED)),
        no_show=Count("id", filter=Q(status=Status.NO_SHOW)),
        cancelled=Count("id", filter=Q(status=Status.CANCELLED)),
        urgent=Count("id", filter=Q(urgency=3) & ~Q(status=Status.CANCELLED)),
        video=Count("id", filter=Q(mode=Appointment.Mode.VIDEO) & ~Q(status=Status.CANCELLED)),
    )
    revenue_today = Appointment.objects.filter(paid_at__date=today).aggregate(s=Sum("fee"))["s"] or 0
    outstanding = Appointment.objects.filter(status=Status.COMPLETED, payment_status=Appointment.Payment.UNPAID)
    beds = Bed.objects.aggregate(
        total=Count("id"),
        occupied=Count("id", filter=Q(status=Bed.Status.OCCUPIED)),
        available=Count("id", filter=Q(status=Bed.Status.AVAILABLE)),
        cleaning=Count("id", filter=Q(status=Bed.Status.CLEANING)),
    )
    wards = Ward.objects.annotate(
        total=Count("beds"), occupied=Count("beds", filter=Q(beds__status=Bed.Status.OCCUPIED))
    )
    start = today - timedelta(days=13)
    trend_raw = {
        row["scheduled_at__date"]: row
        for row in Appointment.objects.filter(scheduled_at__date__gte=start, scheduled_at__date__lte=today)
        .values("scheduled_at__date")
        .annotate(completed=Count("id", filter=Q(status=Status.COMPLETED)),
                  missed=Count("id", filter=Q(status__in=[Status.NO_SHOW, Status.CANCELLED])),
                  other=Count("id", filter=Q(status__in=[Status.BOOKED, Status.CHECKED_IN, Status.IN_PROGRESS])))
    }
    trend = []
    for i in range(14):
        day = start + timedelta(days=i)
        row = trend_raw.get(day, {})
        trend.append({"label": day.strftime("%d %b"), "completed": row.get("completed", 0),
                      "missed": row.get("missed", 0), "open": row.get("other", 0)})
    shown = counts["total"] - counts["no_show"]
    return render(request, "operations/dashboard.html", {
        "counts": counts,
        "revenue_today": revenue_today,
        "outstanding_count": outstanding.count(),
        "outstanding_total": outstanding.aggregate(s=Sum("fee"))["s"] or 0,
        "beds": beds,
        "occupancy": round(100 * beds["occupied"] / beds["total"]) if beds["total"] else 0,
        "wards": wards,
        "load": _doctor_load(today, now),
        "trend": trend,
        "trend_chart": {"labels": [t["label"] for t in trend], "series": [
            {"label": "Completed", "data": [t["completed"] for t in trend], "slot": 0},
            {"label": "Open", "data": [t["open"] for t in trend], "slot": 2},
            {"label": "Missed / cancelled", "data": [t["missed"] for t in trend], "slot": 1},
        ]},
        "attendance": round(100 * shown / counts["total"]) if counts["total"] else 100,
        "pending_doctors": Doctor.objects.filter(is_verified=False).count(),
        "today": today,
    })


@ops_required
def front_desk(request):
    today = services.local_today()
    qs = (Appointment.objects.on_date(today)
          .select_related("patient", "doctor__user", "doctor__specialty")
          .order_by("scheduled_at"))
    doctor = request.GET.get("doctor", "")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if doctor:
        qs = qs.filter(doctor__slug=doctor)
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(patient__first_name__icontains=q)
                       | Q(patient__last_name__icontains=q) | Q(patient__phone__icontains=q))
    return render(request, "operations/front_desk.html", {
        "appointments": qs,
        "doctors": Doctor.objects.listed().select_related("user"),
        "statuses": Status.choices,
        "filters": {"doctor": doctor, "status": status, "q": q},
        "now": timezone.now(),
        "today": today,
    })


@ops_required
@require_POST
def desk_action(request, code):
    appt = get_object_or_404(Appointment, code=code)
    action = request.POST.get("action")
    try:
        if action == "check_in":
            services.check_in(appt)
            messages.success(request, f"{appt.patient.display_name} checked in — token #{appt.token}.")
        elif action == "no_show":
            services.mark_no_show(appt)
            messages.info(request, f"{appt.code} marked as no-show.")
        elif action == "paid":
            services.mark_paid(appt)
            messages.success(request, f"Payment recorded for {appt.code}.")
        elif action == "cancel":
            services.cancel(appt, request.user, request.POST.get("reason", "Cancelled by front desk"))
            messages.info(request, f"{appt.code} cancelled.")
    except services.BookingError as exc:
        messages.error(request, str(exc))
    return redirect_back(request, "operations:front_desk")


@ops_required
def beds(request):
    form = AdmissionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                admission = form.save()
                bed = admission.bed
                bed.status = Bed.Status.OCCUPIED
                bed.save(update_fields=["status", "updated_at"])
        except IntegrityError:
            messages.error(request, "That bed or patient already has an active admission.")
            return redirect("operations:beds")
        AccessLog.record(request, admission.patient, AccessLog.Action.ADMIT, f"Bed {admission.bed}")
        notify(admission.patient, "You've been admitted", f"Ward bed {admission.bed}. Reason: {admission.reason}")
        messages.success(request, f"{admission.patient.display_name} admitted to {admission.bed}.")
        return redirect("operations:beds")
    wards = Ward.objects.prefetch_related("beds__admissions__patient", "beds__admissions__attending__user")
    board = []
    for ward in wards:
        cells = []
        for bed in ward.beds.all():
            current = next((a for a in bed.admissions.all() if a.discharged_at is None), None)
            cells.append({"bed": bed, "admission": current})
        board.append({"ward": ward, "cells": cells,
                      "occupied": sum(1 for c in cells if c["bed"].status == Bed.Status.OCCUPIED)})
    return render(request, "operations/beds.html", {
        "board": board, "form": form, "statuses": Bed.Status.choices,
        "recent": Admission.objects.select_related("patient", "bed__ward")[:8],
    })


@ops_required
@require_POST
def bed_status(request, pk):
    bed = get_object_or_404(Bed, pk=pk)
    status = request.POST.get("status")
    if bed.status == Bed.Status.OCCUPIED or status == Bed.Status.OCCUPIED:
        messages.error(request, "Use admit / discharge to change occupancy.")
    elif status in Bed.Status.values:
        bed.status = status
        bed.save(update_fields=["status", "updated_at"])
        messages.success(request, f"{bed} is now {bed.get_status_display().lower()}.")
    return redirect("operations:beds")


@ops_required
@require_POST
def discharge(request, pk):
    admission = get_object_or_404(Admission, pk=pk, discharged_at__isnull=True)
    with transaction.atomic():
        admission.discharged_at = timezone.now()
        admission.discharge_note = request.POST.get("note", "")[:200]
        admission.save(update_fields=["discharged_at", "discharge_note"])
        admission.bed.status = Bed.Status.CLEANING
        admission.bed.save(update_fields=["status", "updated_at"])
    messages.success(request, f"{admission.patient.display_name} discharged. {admission.bed} flagged for cleaning.")
    return redirect("operations:beds")


@ops_required
def doctors(request):
    return render(request, "operations/doctors.html", {
        "pending": Doctor.objects.filter(is_verified=False).select_related("user", "specialty"),
        "verified": Doctor.objects.filter(is_verified=True).with_ratings().select_related("user", "specialty"),
    })


@ops_required
@require_POST
def verify_doctor(request, pk):
    doctor = get_object_or_404(Doctor, pk=pk)
    doctor.is_verified = request.POST.get("verified") == "1"
    doctor.save(update_fields=["is_verified"])
    if doctor.is_verified:
        notify(doctor.user, "You're verified!", "Your profile is now live and patients can book you.",
               doctor.get_absolute_url(), kind="success", email=True)
        messages.success(request, f"{doctor} verified and listed.")
    else:
        messages.info(request, f"{doctor} hidden from the directory.")
    return redirect("operations:doctors")


def _display_rows(today, now, doctor_slug=None):
    doctors = Doctor.objects.listed().select_related("user", "specialty").prefetch_related("availability")
    if doctor_slug:
        doctors = doctors.filter(slug=doctor_slug)
    doctors = list(doctors)
    states = services.queues_for(doctors, today, now=now)
    rows = []
    for doctor in doctors:
        state = states[doctor.pk]
        if not state.current and not state.waiting:
            continue
        rows.append({"doctor": doctor, "state": state})
    return rows


def queue_display(request):
    """Public waiting-room screen. Shows token numbers only — never names."""
    now = timezone.now()
    today = services.local_today()
    ctx = {"rows": _display_rows(today, now, request.GET.get("doctor")), "now": now}
    template = "operations/_queue_board.html" if request.headers.get("HX-Request") else "operations/queue_display.html"
    return render(request, template, ctx)
