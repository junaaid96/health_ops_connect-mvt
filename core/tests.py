from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from appointments import services
from appointments.models import Appointment, Urgency, WaitlistEntry
from clinic.models import Doctor, Specialty, TimeOff, WeeklyAvailability
from clinic.triage import analyze
from records.models import AccessLog, HealthProfile

Status = Appointment.Status


def make_user(email, role=User.Role.PATIENT, **extra):
    user = User.objects.create_user(username=email.split("@")[0], email=email, password="pw-Secret-123",
                                    first_name=email[:4].title(), last_name="Test", role=role, **extra)
    if role == User.Role.PATIENT:
        HealthProfile.objects.create(user=user)
    return user


@override_settings(TIME_ZONE="UTC", BOOKING_WINDOW_DAYS=14, ALLOWED_HOSTS=["testserver"])
class BaseTestCase(TestCase):
    def setUp(self):
        self.spec = Specialty.objects.create(name="Neurology", slug="neurology", icon="brain")
        self.doc_user = make_user("doc@x.test", role=User.Role.DOCTOR)
        self.doctor = Doctor.objects.create(user=self.doc_user, specialty=self.spec, fee=Decimal("50"),
                                            is_verified=True, offers_video=True)
        for wd in range(7):
            WeeklyAvailability.objects.create(doctor=self.doctor, weekday=wd, start_time=time(0, 0),
                                              end_time=time(23, 40), slot_minutes=20)
        self.patient = make_user("pat@x.test")
        self.other = make_user("oth@x.test")

    def future_slot(self, days=2, index=0, doctor=None):
        day = services.local_today() + timedelta(days=days)
        return [s for s in services.slots_for_day(doctor or self.doctor, day) if s.is_open][index]

    def book(self, patient=None, slot=None, **kw):
        slot = slot or self.future_slot()
        return services.book(patient or self.patient, self.doctor, slot.start, kw.pop("mode", "in_person"),
                             kw.pop("reason", "Headache"), **kw)


class TriageTests(TestCase):
    def test_routes_to_specialty_with_explanation(self):
        result = analyze("Itchy red rash on my arms")
        self.assertEqual(result.matches[0].slug, "dermatology")
        self.assertIn("rash", result.matches[0].matched)

    def test_red_flags_force_urgent(self):
        result = analyze("crushing chest pain and sweating", severity=3)
        self.assertTrue(result.is_emergency)
        self.assertEqual(result.urgency, Urgency.URGENT)

    def test_short_words_do_not_match_inside_other_words(self):
        # "kid" must not match "kidney"; "ear" must not match "heart".
        slugs = analyze("kidney stone").top_slugs
        self.assertNotIn("pediatrics", slugs)
        self.assertNotIn("ent", analyze("my heart races").top_slugs)

    def test_severity_sets_urgency(self):
        self.assertEqual(analyze("cough", severity=6).urgency, Urgency.SOON)
        self.assertEqual(analyze("cough", severity=2).urgency, Urgency.ROUTINE)


class BookingTests(BaseTestCase):
    def test_book_snapshots_fee_and_triage(self):
        appt = self.book(reason="dizzy and headache", severity=9)
        self.assertEqual(appt.fee, Decimal("50"))
        self.assertEqual(appt.urgency, Urgency.URGENT)
        self.assertTrue(appt.code.startswith("HOC-"))
        self.assertTrue(self.patient.notifications.filter(title="Appointment confirmed").exists())

    def test_slot_cannot_be_double_booked(self):
        slot = self.future_slot()
        self.book(slot=slot)
        with self.assertRaises(services.BookingError):
            self.book(patient=self.other, slot=slot)

    def test_cancelled_slot_can_be_rebooked_and_waitlist_notified(self):
        slot = self.future_slot()
        appt = self.book(slot=slot)
        WaitlistEntry.objects.create(patient=self.other, doctor=self.doctor, date=appt.local_date)
        services.cancel(appt, self.patient)
        self.assertTrue(self.other.notifications.filter(title="A slot just opened up").exists())
        self.book(patient=self.other, slot=slot)  # no error

    def test_patient_cannot_double_book_themselves(self):
        slot = self.future_slot()
        self.book(slot=slot)
        other_spec_doc = Doctor.objects.create(user=make_user("d2@x.test", role=User.Role.DOCTOR),
                                               specialty=self.spec, fee=10, is_verified=True)
        WeeklyAvailability.objects.create(doctor=other_spec_doc, weekday=slot.start.weekday(),
                                          start_time=time(0, 0), end_time=time(23, 40))
        with self.assertRaises(services.BookingError):
            services.book(self.patient, other_spec_doc, slot.start, "in_person", "Checkup")

    def test_cannot_book_past_time_off_or_off_schedule(self):
        past = timezone.now() - timedelta(hours=1)
        with self.assertRaises(services.BookingError):
            services.book(self.patient, self.doctor, past.replace(minute=0, second=0, microsecond=0),
                          "in_person", "x")
        slot = self.future_slot(days=3)
        TimeOff.objects.create(doctor=self.doctor, date=slot.start.date())
        with self.assertRaises(services.BookingError):
            self.book(slot=slot)
        with self.assertRaises(services.BookingError):
            self.book(slot=services.Slot(slot.start + timedelta(minutes=7), 20, "open"))

    def test_unverified_doctor_not_bookable(self):
        self.doctor.is_verified = False
        self.doctor.save()
        with self.assertRaises(services.BookingError):
            self.book()

    def test_reschedule_frees_old_slot(self):
        first, second = self.future_slot(index=0), self.future_slot(index=1)
        appt = self.book(slot=first)
        services.reschedule(appt, second.start, self.patient)
        appt.refresh_from_db()
        self.assertEqual(appt.scheduled_at, second.start)
        self.book(patient=self.other, slot=first)


class QueueTests(BaseTestCase):
    def _checked_in(self, patient, urgency, minutes_ago):
        now = timezone.now()
        return Appointment.objects.create(
            patient=patient, doctor=self.doctor, scheduled_at=now + timedelta(minutes=10 + minutes_ago),
            reason="x", status=Status.CHECKED_IN, urgency=urgency,
            checked_in_at=now - timedelta(minutes=minutes_ago), queue_number=minutes_ago)

    def test_check_in_assigns_sequential_tokens(self):
        now = timezone.now()
        slots = [s for s in services.slots_for_day(self.doctor, services.local_today()) if s.is_open]
        if len(slots) < 2:
            self.skipTest("Not enough slots left today")
        a = self.book(slot=slots[0])
        b = self.book(patient=self.other, slot=slots[1])
        services.check_in(a, now=a.scheduled_at - timedelta(minutes=5))
        services.check_in(b, now=b.scheduled_at - timedelta(minutes=5))
        self.assertEqual((a.queue_number, b.queue_number), (1, 2))
        self.assertEqual(a.status, Status.CHECKED_IN)

    def test_check_in_window_enforced(self):
        appt = self.book(slot=self.future_slot(days=3))
        with self.assertRaises(services.BookingError):
            services.check_in(appt)

    def test_urgent_patients_jump_the_queue(self):
        routine = self._checked_in(self.patient, Urgency.ROUTINE, 30)
        urgent = self._checked_in(self.other, Urgency.URGENT, 2)
        state = services.queue_for(self.doctor)
        self.assertEqual([e.appointment for e in state.waiting], [urgent, routine])
        self.assertLess(state.waiting[0].wait_minutes, state.waiting[1].wait_minutes)

    def test_call_next_starts_consultation_and_notifies(self):
        appt = self._checked_in(self.patient, Urgency.ROUTINE, 5)
        started = services.call_next(self.doctor)
        self.assertEqual(started, appt)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Status.IN_PROGRESS)
        self.assertTrue(self.patient.notifications.filter(title="It's your turn").exists())
        with self.assertRaises(services.BookingError):
            services.call_next(self.doctor)  # busy with the current patient


class HealthRecordTests(TestCase):
    def test_allergy_conflicts(self):
        profile = HealthProfile(allergies="Penicillin, peanuts")
        self.assertEqual(profile.allergy_conflicts(["Penicillin V", "Paracetamol"]), [("Penicillin V", "penicillin")])
        self.assertEqual(HealthProfile(allergies="None").allergy_conflicts(["None tablet"]), [])

    def test_completeness(self):
        self.assertEqual(HealthProfile().completeness, 0)
        self.assertEqual(HealthProfile(allergies="none").completeness, 14)


class ViewTests(BaseTestCase):
    def login(self, user):
        self.client.force_login(user)

    def test_public_pages(self):
        for url in ["/", reverse("clinic:directory"), self.doctor.get_absolute_url(),
                    reverse("clinic:care_finder") + "?symptoms=rash", reverse("operations:queue_display"),
                    reverse("accounts:login"), reverse("accounts:signup")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_signup_creates_patient_with_passport(self):
        response = self.client.post(reverse("accounts:signup"), {
            "first_name": "New", "last_name": "Person", "email": "new@x.test", "phone": "",
            "password1": "a-Strong-pass-99", "password2": "a-Strong-pass-99"})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="new@x.test")
        self.assertTrue(user.is_patient)
        self.assertTrue(HealthProfile.objects.filter(user=user).exists())

    def test_login_with_email(self):
        response = self.client.post(reverse("accounts:login"), {"username": "pat@x.test", "password": "pw-Secret-123"})
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_booking_flow(self):
        self.login(self.patient)
        slot = self.future_slot()
        url = reverse("appointments:book", args=[self.doctor.slug]) + f"?start={slot.iso}"
        self.assertEqual(self.client.get(url.replace("+", "%2B")).status_code, 200)
        response = self.client.post(url.replace("+", "%2B"), {
            "start": slot.iso, "mode": "video", "reason": "Migraine", "symptoms": "", "severity": 4,
            "symptom_duration": "days", "consent": "on"})
        appt = Appointment.objects.get(patient=self.patient)
        self.assertRedirects(response, appt.get_absolute_url() + "?booked=1", fetch_redirect_response=False)
        self.assertEqual(appt.mode, "video")
        self.assertEqual(self.client.get(appt.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(reverse("appointments:ics", args=[appt.code]))["Content-Type"],
                         "text/calendar; charset=utf-8")

    def test_other_patients_cannot_see_appointment(self):
        appt = self.book()
        self.login(self.other)
        self.assertEqual(self.client.get(appt.get_absolute_url()).status_code, 404)

    def test_role_gates(self):
        self.login(self.patient)
        self.assertEqual(self.client.get(reverse("operations:dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("clinic:schedule")).status_code, 403)
        self.login(self.doc_user)
        self.assertEqual(self.client.get(reverse("records:health")).status_code, 403)

    def test_consultation_completes_visit_and_logs_access(self):
        appt = self.book()
        Appointment.objects.filter(pk=appt.pk).update(
            status=Status.IN_PROGRESS, started_at=timezone.now(), scheduled_at=timezone.now())
        self.patient.health.allergies = "Amoxicillin"
        self.patient.health.save()
        self.login(self.doc_user)
        url = reverse("records:consult", args=[appt.code])
        data = {"action": "complete", "c-diagnosis": "Migraine", "c-clinical_notes": "", "c-advice": "Rest",
                "c-follow_up_in_days": "", "rx-TOTAL_FORMS": 1, "rx-INITIAL_FORMS": 0, "rx-MIN_NUM_FORMS": 0,
                "rx-MAX_NUM_FORMS": 15, "rx-0-medicine": "Amoxicillin", "rx-0-dosage": "500 mg",
                "rx-0-frequency": "1-0-1", "rx-0-duration": "5 days", "rx-0-instructions": ""}
        # Allergy conflict blocks the first attempt...
        self.assertEqual(self.client.post(url, data).status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Status.IN_PROGRESS)
        # ...and goes through once the doctor explicitly overrides.
        self.client.post(url, {**data, "c-confirm_allergy_override": "on"})
        appt.refresh_from_db()
        self.assertEqual(appt.status, Status.COMPLETED)
        self.assertTrue(appt.consultation.allergy_override)
        self.assertTrue(AccessLog.objects.filter(patient=self.patient, action="prescribe").exists())
        verify = self.client.get(reverse("records:verify", args=[appt.consultation.verification_code]))
        self.assertContains(verify, "Genuine prescription")

    def test_healthz(self):
        self.assertEqual(self.client.get("/healthz").json()["database"], "ok")
