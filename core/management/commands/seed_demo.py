"""Populate the database with a realistic demo hospital.

    python manage.py seed_demo            # first run: everything
    python manage.py seed_demo --today    # refresh today's live queue (run daily for demos)

Demo logins (password for all: see DEMO_PASSWORD):
    patient@demo.health · doctor@demo.health · ops@demo.health · admin@demo.health
"""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.models import Notification, User
from appointments.models import Appointment, Urgency, generate_code
from appointments.services import _generate, local_today
from clinic.models import Doctor, Review, Specialty, WeeklyAvailability
from operations.models import Admission, Bed, Ward
from records.models import AccessLog, Consultation, HealthProfile, PrescriptionItem, VitalReading

DEMO_PASSWORD = "HealthOps!2026"
SEED_DIR = Path(__file__).resolve().parents[2] / "seed" / "doctors"
Status = Appointment.Status

SPECIALTIES = [
    ("General Medicine", "general-medicine", "stethoscope", "Fevers, infections, check-ups and anything you're unsure about."),
    ("Cardiology", "cardiology", "heart-pulse", "Heart rhythm, blood pressure and cholesterol."),
    ("Dermatology", "dermatology", "sparkles", "Skin, hair and nail conditions."),
    ("Pediatrics", "pediatrics", "baby", "Care for infants, children and teens."),
    ("Orthopedics", "orthopedics", "bone", "Bones, joints, sports injuries and back pain."),
    ("Neurology", "neurology", "brain", "Headaches, dizziness, nerves and memory."),
    ("Gastroenterology", "gastroenterology", "soup", "Stomach, digestion and liver."),
    ("ENT", "ent", "ear", "Ear, nose, throat and sinuses."),
    ("Gynecology & Obstetrics", "gynecology", "flower-2", "Women's health, pregnancy and fertility."),
    ("Psychiatry", "psychiatry", "smile", "Anxiety, mood, sleep and mental wellbeing."),
    ("Ophthalmology", "ophthalmology", "eye", "Eyes and vision."),
    ("Endocrinology", "endocrinology", "droplets", "Diabetes, thyroid and hormones."),
    ("Pulmonology", "pulmonology", "wind", "Asthma, breathing and lungs."),
]

# (first, last, photo, specialty, title, qualifications, years, fee, languages, schedule pattern, video)
DOCTORS = [
    ("Nadia", "Rahman", "doc-1", "neurology", "Senior Consultant", "MBBS, MD (Neurology)", 12, 80, "English, Bengali", "A", True),
    ("Priya", "Sharma", "doc-2", "dermatology", "Consultant", "MBBS, DDV", 8, 60, "English, Hindi", "B", True),
    ("Arif", "Hasan", "doc-3", "cardiology", "Professor & Head", "MBBS, FCPS, FACC", 24, 120, "English, Bengali", "A", False),
    ("Ayesha", "Siddiqui", "doc-4", "gynecology", "Consultant", "MBBS, FCPS (Obs & Gynae)", 10, 75, "English, Urdu", "C", True),
    ("Rakesh", "Menon", "doc-5", "general-medicine", "Senior Physician", "MBBS, MD (Internal Medicine)", 20, 40, "English, Malayalam", "D", True),
    ("Meera", "Iyer", "doc-6", "pediatrics", "Consultant Pediatrician", "MBBS, DCH, MRCPCH", 9, 55, "English, Tamil", "B", True),
    ("Farhana", "Akter", "doc-7", "endocrinology", "Associate Professor", "MBBS, MD (Endocrinology)", 14, 70, "English, Bengali", "C", True),
    ("Imran", "Kabir", "doc-8", "orthopedics", "Senior Consultant", "MBBS, MS (Ortho)", 16, 90, "English, Bengali", "A", False),
    ("Sanjay", "Verma", "doc-9", "gastroenterology", "Consultant", "MBBS, DM (Gastro)", 11, 85, "English, Hindi", "D", True),
    ("Daniel", "Clark", "doc-10", "ent", "Consultant Surgeon", "MBBS, FRCS (ENT)", 13, 70, "English", "B", False),
    ("Michael", "Stone", "doc-11", "pulmonology", "Senior Consultant", "MD, FCCP", 22, 95, "English", "C", True),
    ("James", "Carter", "doc-12", "psychiatry", "Consultant Psychiatrist", "MD, MRCPsych", 7, 65, "English", "E", True),
    ("Emily", "Watson", "doc-13", "ophthalmology", "Consultant", "MBBS, MS (Ophthalmology)", 9, 60, "English", "D", False),
    ("Tasnim", "Chowdhury", "doc-14", "general-medicine", "Family Physician", "MBBS, CCD", 6, 30, "English, Bengali", "E", True),
]

# Weekday blocks: (weekdays, start, end, slot minutes). Weekday 0 = Monday.
PATTERNS = {
    "A": [(range(0, 6), "09:00", "13:00", 20)],
    "B": [(range(0, 7), "10:00", "13:00", 15), ((0, 2, 4), "16:00", "19:00", 15)],
    "C": [(range(0, 6), "14:00", "18:00", 20)],
    "D": [(range(0, 7), "08:30", "12:30", 15), ((1, 3, 5), "17:00", "20:00", 15)],
    "E": [(range(0, 7), "11:00", "15:00", 30), ((0, 1, 2, 3), "18:00", "21:00", 30)],
}

PATIENT_NAMES = [
    ("Rahim", "Uddin"), ("Sadia", "Islam"), ("Tanvir", "Ahmed"), ("Nusrat", "Jahan"), ("Karim", "Hossain"),
    ("Lamia", "Khan"), ("Omar", "Faruk"), ("Anika", "Roy"), ("Zubair", "Alam"), ("Maliha", "Chowdhury"),
    ("Ravi", "Patel"), ("Sneha", "Nair"), ("Arjun", "Das"), ("Fatima", "Begum"), ("Hasan", "Mahmud"),
    ("Elena", "Garcia"), ("Liam", "Walsh"), ("Grace", "Kim"), ("Noah", "Brown"), ("Aisha", "Yusuf"),
    ("Samuel", "Okafor"), ("Mina", "Tanaka"), ("Leo", "Martins"), ("Zara", "Ali"), ("Ibrahim", "Sheikh"),
    ("Chloe", "Dubois"), ("Farid", "Rahman"), ("Joya", "Sen"), ("Kabir", "Mehta"), ("Rina", "Paul"),
]

CASES = {
    "neurology": [("Recurring headaches", "headache behind the eyes, worse in the evening", "Tension-type headache",
                   [("Paracetamol", "500 mg", "1-0-1 after meals", "5 days", "Max 4 tablets a day")]),
                  ("Dizziness when standing", "dizzy for a few seconds after standing up", "Benign positional vertigo",
                   [("Betahistine", "16 mg", "1-0-1", "10 days", "")])],
    "dermatology": [("Itchy rash on arms", "red itchy patches for two weeks", "Contact dermatitis",
                     [("Hydrocortisone cream 1%", "Thin layer", "Twice daily", "7 days", "Avoid face"),
                      ("Cetirizine", "10 mg", "0-0-1", "7 days", "May cause drowsiness")]),
                    ("Acne flare-up", "painful pimples on cheeks", "Acne vulgaris (moderate)",
                     [("Adapalene gel 0.1%", "Pea-sized", "At night", "8 weeks", "Use sunscreen")])],
    "cardiology": [("High blood pressure readings", "home BP around 150/95", "Stage 2 hypertension",
                    [("Amlodipine", "5 mg", "1-0-0", "30 days", "Check BP weekly")]),
                   ("Palpitations", "heart racing at night", "Sinus tachycardia — anxiety related",
                    [("Propranolol", "10 mg", "As needed", "14 days", "Max twice daily")])],
    "gynecology": [("Irregular periods", "cycles between 35 and 50 days", "Suspected PCOS",
                    [("Metformin", "500 mg", "0-0-1 with dinner", "30 days", "")]),
                   ("Pregnancy check-up", "12 weeks pregnant, routine visit", "Normal pregnancy, first trimester",
                    [("Folic acid", "5 mg", "1-0-0", "90 days", "")])],
    "general-medicine": [("Fever and sore throat", "fever 38.5 for two days with sore throat", "Acute pharyngitis",
                          [("Paracetamol", "500 mg", "1-1-1", "3 days", "Only if fever"),
                           ("Azithromycin", "500 mg", "1-0-0", "3 days", "Complete the course")]),
                         ("Annual check-up", "routine health check", "Healthy adult — routine screening",
                          [])],
    "pediatrics": [("My child has a cough", "dry cough for 5 days, no fever", "Viral upper respiratory infection",
                    [("Honey & warm fluids", "1 tsp", "Twice daily", "5 days", "Not for under 1 year")]),
                   ("Vaccination visit", "due for scheduled vaccines", "Routine immunisation", [])],
    "endocrinology": [("Diabetes follow-up", "fasting sugar around 160", "Type 2 diabetes — suboptimal control",
                       [("Metformin", "1000 mg", "1-0-1 with meals", "30 days", "")]),
                      ("Thyroid results review", "tired and gaining weight", "Hypothyroidism",
                       [("Levothyroxine", "50 mcg", "1-0-0 empty stomach", "30 days", "")])],
    "orthopedics": [("Knee pain after running", "knee pain for 3 weeks", "Patellofemoral pain syndrome",
                     [("Ibuprofen", "400 mg", "1-0-1 after meals", "5 days", "Stop if stomach upset")]),
                    ("Lower back pain", "back pain after lifting", "Mechanical low back strain",
                     [("Naproxen", "250 mg", "1-0-1 after meals", "5 days", "")])],
    "gastroenterology": [("Acidity and heartburn", "burning after meals for a month", "GERD",
                          [("Omeprazole", "20 mg", "1-0-0 before breakfast", "28 days", "")]),
                         ("Stomach pain and bloating", "bloating most evenings", "Functional dyspepsia",
                          [("Domperidone", "10 mg", "1-1-1 before meals", "7 days", "")])],
    "ent": [("Blocked nose and sinus pain", "blocked nose for 10 days", "Acute sinusitis",
             [("Mometasone nasal spray", "2 sprays", "Once daily", "14 days", "")]),
            ("Earache", "right ear pain since yesterday", "Otitis externa",
             [("Ciprofloxacin ear drops", "3 drops", "Twice daily", "7 days", "Keep ear dry")])],
    "pulmonology": [("Asthma getting worse", "wheezing at night", "Asthma — partly controlled",
                     [("Salbutamol inhaler", "2 puffs", "As needed", "30 days", "Use spacer"),
                      ("Montelukast", "10 mg", "0-0-1", "30 days", "")]),
                    ("Chronic cough", "cough for 6 weeks", "Post-viral cough", [])],
    "psychiatry": [("Anxiety and poor sleep", "anxious most days, can't sleep", "Generalised anxiety disorder",
                    [("Sertraline", "25 mg", "1-0-0", "30 days", "Review in 4 weeks")]),
                   ("Low mood", "feeling sad and tired for weeks", "Mild depressive episode", [])],
    "ophthalmology": [("Blurry vision", "blurry when reading", "Presbyopia", []),
                      ("Red itchy eyes", "red watery eyes", "Allergic conjunctivitis",
                       [("Olopatadine eye drops", "1 drop", "Twice daily", "14 days", "")])],
}

REVIEW_COMMENTS = [
    "Listened carefully and explained everything clearly.",
    "The live queue meant I waited in the café instead of the corridor. Brilliant.",
    "Very thorough. The prescription was ready on my phone before I left.",
    "Kind, patient and on time.",
    "Great doctor, the check-in from my phone was so easy.",
    "Took my concerns seriously and followed up the next day.",
    "", "", "",
]


def _install_photo(photo, first, last):
    """Upload a bundled demo photo to the default storage (local disk or the
    object-storage bucket) under a deterministic name. Idempotent, so it can
    also restore photos on hosts with an ephemeral disk (see --media)."""
    src = SEED_DIR / f"{photo}.webp"
    name = f"doctors/{first.lower()}-{last.lower()}.webp"
    if not src.exists():
        return ""
    if not default_storage.exists(name):
        with src.open("rb") as fh:
            name = default_storage.save(name, File(fh, name=name))
    return name


class Command(BaseCommand):
    help = "Seed a realistic demo hospital (doctors, patients, visits, queue, beds)."

    def add_arguments(self, parser):
        parser.add_argument("--today", action="store_true", help="Only (re)generate today's live queue activity.")
        parser.add_argument("--media", action="store_true", help="Only restore bundled demo doctor photos.")
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args, **opts):
        self.rng = random.Random(opts["seed"])
        self.now = timezone.now()
        self.today = local_today()
        if opts["media"]:
            restored = 0
            for first, last, photo, *_ in DOCTORS:
                if _install_photo(photo, first, last):
                    restored += 1
            self.stdout.write(self.style.SUCCESS(f"Demo photos present in storage: {restored}."))
            return
        with transaction.atomic():
            if opts["today"]:
                self._today_activity(refresh=True)
                self._demo_patient_today()
                self.stdout.write(self.style.SUCCESS("Today's queue refreshed."))
                return
            if Doctor.objects.exists():
                self.stdout.write(self.style.WARNING("Demo data already present — refreshing today's queue only."))
                self._today_activity(refresh=True)
                self._demo_patient_today()
                return
            self._specialties()
            self._doctors()
            self._people()
            self._history()
            self._future()
            self._today_activity(refresh=False)
            self._demo_patient_story()
            self._wards()
        self.stdout.write(self.style.SUCCESS(
            f"Demo hospital ready. Sign in with patient@demo.health / doctor@demo.health / ops@demo.health "
            f"/ admin@demo.health — password {DEMO_PASSWORD}"))

    # --- reference data -----------------------------------------------------
    def _specialties(self):
        self.specialties = {}
        for name, slug, icon, desc in SPECIALTIES:
            self.specialties[slug] = Specialty.objects.create(name=name, slug=slug, icon=icon, description=desc)

    def _user(self, email, first, last, role, **extra):
        user = User(username=email.split("@")[0].replace(".", "")[:30], email=email, first_name=first,
                    last_name=last, role=role, email_verified=True, **extra)
        user.set_password(DEMO_PASSWORD)
        user.save()
        return user

    def _doctors(self):
        self.doctors = []
        for i, (first, last, photo, spec, title, quals, years, fee, langs, pattern, video) in enumerate(DOCTORS):
            email = "doctor@demo.health" if i == 0 else f"{first.lower()}.{last.lower()}@demo.health"
            user = self._user(email, first, last, User.Role.DOCTOR, phone=f"+1555010{i:02d}")
            doctor = Doctor(
                user=user, specialty=self.specialties[spec], title=title, qualifications=quals,
                years_experience=years, fee=Decimal(fee), languages=langs,
                license_number=f"MD-{20000 + i * 137}", room=f"Room {200 + i}, Block {'AB'[i % 2]}",
                offers_in_person=True, offers_video=video, is_verified=True,
                bio=(f"Dr. {first} {last} is a {title.lower()} in {self.specialties[spec].name.lower()} with "
                     f"{years} years of experience. Known for clear explanations and shared decision-making, "
                     f"{first} believes the best care starts with really listening."),
            )
            doctor.photo.name = _install_photo(photo, first, last)
            doctor.save()
            for days, start, end, minutes in PATTERNS[pattern]:
                for wd in days:
                    WeeklyAvailability.objects.create(
                        doctor=doctor, weekday=wd, start_time=time.fromisoformat(start),
                        end_time=time.fromisoformat(end), slot_minutes=minutes)
            self.doctors.append(doctor)
        # One pending application for the verification workflow.
        pending = self._user("kamal.uddin@demo.health", "Kamal", "Uddin", User.Role.DOCTOR)
        Doctor.objects.create(user=pending, specialty=self.specialties["pulmonology"], title="Consultant",
                              qualifications="MBBS, MD (Chest Medicine)", years_experience=5, fee=Decimal(50),
                              license_number="MD-99812", is_verified=False, bio="Applied via the doctor portal.")

    def _people(self):
        self.ops = self._user("ops@demo.health", "Olivia", "Park", User.Role.STAFF)
        admin = self._user("admin@demo.health", "Admin", "User", User.Role.STAFF, is_staff=True, is_superuser=True)
        admin.save()
        self.patient = self._user("patient@demo.health", "Sara", "Ahmed", User.Role.PATIENT, phone="+15550199")
        HealthProfile.objects.create(
            user=self.patient, date_of_birth=self.today.replace(year=self.today.year - 34), sex="female",
            blood_group="B+", height_cm=162, allergies="Penicillin", chronic_conditions="Migraine",
            current_medications="Vitamin D3 1000 IU", emergency_contact_name="Rafiq Ahmed",
            emergency_contact_phone="+15550198")
        self.patients = [self.patient]
        bloods = [g for g, _ in HealthProfile.BLOOD_GROUPS]
        for i, (first, last) in enumerate(PATIENT_NAMES):
            user = self._user(f"{first.lower()}.{last.lower()}@example.com", first, last, User.Role.PATIENT,
                              phone=f"+1555020{i:02d}")
            HealthProfile.objects.create(
                user=user, date_of_birth=self.today.replace(year=self.today.year - self.rng.randint(4, 78)),
                sex=self.rng.choice(["female", "male"]), blood_group=self.rng.choice(bloods),
                height_cm=self.rng.randint(120, 188),
                allergies=self.rng.choice(["None", "None", "None", "Sulfa drugs", "Peanuts", "Ibuprofen", "Dust"]),
                chronic_conditions=self.rng.choice(["", "", "Hypertension", "Type 2 diabetes", "Asthma"]),
                emergency_contact_name="Family contact", emergency_contact_phone=f"+1555030{i:02d}")
            self.patients.append(user)

    # --- appointments -------------------------------------------------------
    def _slots(self, doctor, day):
        return list(_generate(list(doctor.availability.all()), day))

    def _new_appt(self, doctor, patient, start, minutes, status, **extra):
        spec = doctor.specialty.slug
        reason, symptoms, *_ = self.rng.choice(CASES.get(spec, CASES["general-medicine"]))
        severity = self.rng.choice([2, 3, 3, 4, 5, 6, 7, 8])
        urgency = Urgency.URGENT if severity >= 8 else Urgency.SOON if severity >= 5 else Urgency.ROUTINE
        mode = Appointment.Mode.VIDEO if doctor.offers_video and self.rng.random() < 0.25 else Appointment.Mode.IN_PERSON
        return Appointment(
            code=generate_code(), patient=patient, doctor=doctor, scheduled_at=start, duration_minutes=minutes,
            mode=mode, status=status, reason=reason[:200], symptoms=symptoms.capitalize(), severity=severity,
            symptom_duration=self.rng.choice(["days", "days", "weeks", "hours"]), urgency=urgency, fee=doctor.fee,
            **extra,
        )

    def _finish(self, appt, minutes):
        appt.checked_in_at = appt.scheduled_at - timedelta(minutes=self.rng.randint(3, 25))
        appt.started_at = appt.scheduled_at + timedelta(minutes=self.rng.randint(0, 12))
        appt.completed_at = appt.started_at + timedelta(minutes=max(6, minutes + self.rng.randint(-6, 6)))
        appt.payment_status = Appointment.Payment.PAID if self.rng.random() < 0.9 else Appointment.Payment.UNPAID
        appt.paid_at = appt.completed_at if appt.payment_status == Appointment.Payment.PAID else None

    def _history(self, days=28):
        appts = []
        for doctor in self.doctors:
            for back in range(days, 0, -1):
                day = self.today - timedelta(days=back)
                for start, minutes in self._slots(doctor, day):
                    if self.rng.random() > 0.32:
                        continue
                    roll = self.rng.random()
                    status = Status.COMPLETED if roll < 0.82 else Status.NO_SHOW if roll < 0.9 else Status.CANCELLED
                    appt = self._new_appt(doctor, self.rng.choice(self.patients[1:]), start, minutes, status)
                    if status == Status.COMPLETED:
                        self._finish(appt, minutes)
                        appt.queue_number = None
                    elif status == Status.CANCELLED:
                        appt.cancelled_at = start - timedelta(hours=self.rng.randint(2, 48))
                        appt.cancel_reason = "Feeling better"
                    appts.append(appt)
        Appointment.objects.bulk_create(appts, batch_size=500)
        self._consultations(Appointment.objects.filter(status=Status.COMPLETED, consultation__isnull=True)
                            .select_related("doctor__specialty"))

    def _consultations(self, completed, review_rate=0.45):
        consults, reviews = [], []
        for appt in completed:
            spec = appt.doctor.specialty.slug
            case = next((c for c in CASES.get(spec, []) if c[0] == appt.reason), None) or \
                self.rng.choice(CASES.get(spec, CASES["general-medicine"]))
            consults.append((Consultation(
                appointment=appt, diagnosis=case[2], clinical_notes=f"Presented with {case[1]}. Examination unremarkable otherwise.",
                advice="Rest, stay hydrated and return if symptoms worsen.",
                follow_up_in_days=self.rng.choice([None, None, 7, 14, 30]),
            ), case[3]))
            if self.rng.random() < review_rate:
                reviews.append(Review(appointment=appt, doctor=appt.doctor, patient=appt.patient,
                                      rating=self.rng.choice([5, 5, 5, 4, 4, 4, 3]),
                                      comment=self.rng.choice(REVIEW_COMMENTS)))
        created = Consultation.objects.bulk_create([c for c, _ in consults], batch_size=500)
        items = []
        for consultation, (_, meds) in zip(created, consults):
            for med, dose, freq, dur, instr in meds:
                items.append(PrescriptionItem(consultation=consultation, medicine=med, dosage=dose,
                                              frequency=freq, duration=dur, instructions=instr))
        PrescriptionItem.objects.bulk_create(items, batch_size=1000)
        reviews = Review.objects.bulk_create(reviews, batch_size=500)
        # Backdate to the visit so timelines read naturally.
        for obj in (*created, *reviews):
            obj.created_at = obj.appointment.completed_at or self.now
        Consultation.objects.bulk_update(created, ["created_at"], batch_size=500)
        Review.objects.bulk_update(reviews, ["created_at"], batch_size=500)

    def _future(self, days=10):
        appts = []
        for doctor in self.doctors:
            for ahead in range(1, days):
                day = self.today + timedelta(days=ahead)
                for start, minutes in self._slots(doctor, day):
                    if self.rng.random() < 0.3 - ahead * 0.02:
                        appts.append(self._new_appt(doctor, self.rng.choice(self.patients[1:]), start, minutes,
                                                    Status.BOOKED))
        Appointment.objects.bulk_create(appts, batch_size=500)

    def _today_activity(self, refresh):
        """Build a believable 'right now': finished visits this morning, one
        patient with the doctor, a few checked in and waiting, later bookings."""
        doctors = list(Doctor.objects.listed().prefetch_related("availability").select_related("specialty"))
        patients = list(User.objects.filter(role=User.Role.PATIENT, email__endswith="@example.com"))
        if not doctors or not patients:
            return
        if refresh:
            # Only ever touches the synthetic demo patients (…@example.com), never real users.
            Appointment.objects.on_date(self.today).filter(patient__email__endswith="@example.com").delete()
        self.doctors = doctors
        for doctor in doctors:
            slots = self._slots(doctor, self.today)
            if not slots:
                continue
            taken = set(Appointment.objects.filter(doctor=doctor).on_date(self.today)
                        .exclude(status=Status.CANCELLED).values_list("scheduled_at", flat=True))
            past = [s for s in slots if s[0] + timedelta(minutes=s[1]) <= self.now]
            future = [s for s in slots if s[0] + timedelta(minutes=s[1]) > self.now]
            # If clinic hours are over (or not started), still show a live queue using the
            # nearest slots so the demo always has something happening.
            queue_slots = future[:4] if future else past[-4:]
            done_slots = [s for s in past if s not in queue_slots][-6:]
            later = future[4:]
            pool = self.rng.sample(patients, min(len(patients), 12))
            created = []
            q = 0
            for start, minutes in done_slots:
                if start in taken or self.rng.random() < 0.3:
                    continue
                appt = self._new_appt(doctor, pool.pop(), start, minutes, Status.COMPLETED)
                self._finish(appt, minutes)
                q += 1
                appt.queue_number = q
                appt.started_at = min(appt.started_at, self.now - timedelta(minutes=minutes + 5))
                appt.completed_at = min(appt.completed_at, self.now - timedelta(minutes=2))
                if appt.completed_at <= appt.started_at:
                    appt.completed_at = appt.started_at + timedelta(minutes=minutes)
                created.append(appt)
            for idx, (start, minutes) in enumerate(queue_slots):
                if start in taken or not pool:
                    continue
                q += 1
                if idx == 0:
                    appt = self._new_appt(doctor, pool.pop(), start, minutes, Status.IN_PROGRESS)
                    appt.checked_in_at = self.now - timedelta(minutes=self.rng.randint(15, 30))
                    appt.started_at = self.now - timedelta(minutes=self.rng.randint(2, 9))
                else:
                    appt = self._new_appt(doctor, pool.pop(), start, minutes, Status.CHECKED_IN)
                    appt.checked_in_at = self.now - timedelta(minutes=self.rng.randint(1, 14))
                appt.mode = Appointment.Mode.IN_PERSON
                appt.queue_number = q
                created.append(appt)
            for start, minutes in later:
                if start in taken or not pool or self.rng.random() < 0.55:
                    continue
                created.append(self._new_appt(doctor, pool.pop(), start, minutes, Status.BOOKED))
            Appointment.objects.bulk_create(created)
        self._consultations(Appointment.objects.filter(status=Status.COMPLETED, consultation__isnull=True)
                            .select_related("doctor__specialty"), review_rate=0.3)

    def _demo_patient_story(self):
        """Give the demo patient a rich, current record to explore."""
        patient = self.patient
        neuro = Doctor.objects.prefetch_related("availability").get(user__email="doctor@demo.health")
        derm = next(d for d in self.doctors if d.specialty.slug == "dermatology")
        gp = next(d for d in self.doctors if d.specialty.slug == "general-medicine")

        # Past completed visits with prescriptions (one left un-reviewed to show the prompt).
        for back, doctor, reviewed in ((24, gp, True), (9, neuro, False)):
            day = self.today - timedelta(days=back)
            slot = next((s for s in self._slots(doctor, day)
                         if not Appointment.objects.filter(doctor=doctor, scheduled_at=s[0]).exists()), None)
            if not slot:
                continue
            appt = self._new_appt(doctor, patient, slot[0], slot[1], Status.COMPLETED)
            self._finish(appt, slot[1])
            appt.save()
            self._consultations([appt], review_rate=1.0 if reviewed else 0.0)

        self._demo_patient_today()

        # A future video visit.
        for ahead in range(2, 9):
            day = self.today + timedelta(days=ahead)
            slot = next((s for s in self._slots(derm, day)
                         if not Appointment.objects.filter(doctor=derm, scheduled_at=s[0]).exists()), None)
            if slot:
                appt = self._new_appt(derm, patient, slot[0], slot[1], Status.BOOKED)
                appt.mode = Appointment.Mode.VIDEO
                appt.reason, appt.symptoms, appt.severity, appt.urgency = \
                    "Itchy rash on arms", "Red itchy patches on both forearms for two weeks", 3, Urgency.ROUTINE
                appt.save()
                break

        # Two months of home vitals with a gentle BP trend.
        readings = []
        for i in range(24):
            at = self.now - timedelta(days=60 - i * 2.5, hours=self.rng.randint(0, 5))
            readings.append(VitalReading(
                patient=patient, recorded_by=patient, recorded_at=at,
                systolic=self.rng.randint(124, 142) - i // 3, diastolic=self.rng.randint(80, 92) - i // 5,
                heart_rate=self.rng.randint(64, 88), glucose=Decimal(self.rng.randint(88, 118)),
                weight_kg=Decimal("68.5") - Decimal(i) / 10, spo2=self.rng.randint(96, 99),
            ))
        VitalReading.objects.bulk_create(readings)

        AccessLog.objects.bulk_create([
            AccessLog(patient=patient, actor=neuro.user, action=AccessLog.Action.CONSULT, detail="Visit review"),
            AccessLog(patient=patient, actor=gp.user, action=AccessLog.Action.PRESCRIBE, detail="Acute pharyngitis"),
        ])
        Notification.objects.bulk_create([
            Notification(user=patient, kind="success", title="You're checked in",
                         body=f"Token issued for your visit with {neuro}. We'll notify you when it's your turn."),
            Notification(user=patient, kind="info", title="How was your visit?",
                         body=f"Rate your recent visit with {neuro} to help other patients."),
        ])

    def _demo_patient_today(self):
        """The demo patient is checked in with the demo doctor today."""
        patient = User.objects.filter(email="patient@demo.health").first()
        neuro = Doctor.objects.filter(user__email="doctor@demo.health").prefetch_related("availability").first()
        if not patient or not neuro or Appointment.objects.filter(patient=patient).on_date(self.today).exists():
            return
        slots = self._slots(neuro, self.today)
        free = [s for s in slots if not Appointment.objects.filter(doctor=neuro, scheduled_at=s[0]).exclude(
            status=Status.CANCELLED).exists()]
        upcoming = [s for s in free if s[0] > self.now] or free[-1:]
        if upcoming:
            start, minutes = upcoming[0]
            appt = self._new_appt(neuro, patient, start, minutes, Status.CHECKED_IN)
            appt.reason, appt.symptoms, appt.severity = "Migraine getting more frequent", \
                "Three migraines this week with nausea and light sensitivity", 6
            appt.urgency = Urgency.SOON
            appt.checked_in_at = self.now - timedelta(minutes=4)
            last = Appointment.objects.filter(doctor=neuro).on_date(self.today).aggregate(
                m=Max("queue_number"))["m"] or 0
            appt.queue_number = last + 1
            appt.mode = Appointment.Mode.IN_PERSON
            appt.save()

    def _wards(self):
        layout = [("General Ward A", "GWA", "general", "2nd floor", 12), ("Intensive Care", "ICU", "icu", "3rd floor", 6),
                  ("Maternity", "MAT", "maternity", "4th floor", 8), ("Pediatrics", "PED", "pediatric", "4th floor", 8),
                  ("Surgical Recovery", "SRG", "surgical", "3rd floor", 10)]
        patients = list(User.objects.filter(role=User.Role.PATIENT).exclude(email="patient@demo.health"))
        self.rng.shuffle(patients)
        reasons = ["Post-operative observation", "Pneumonia — IV antibiotics", "Dehydration", "Chest pain observation",
                   "Fracture management", "Asthma exacerbation", "Labour & delivery", "Diabetic ketoacidosis"]
        for name, code, kind, floor, count in layout:
            ward = Ward.objects.create(name=name, code=code, kind=kind, floor=floor)
            for n in range(1, count + 1):
                roll = self.rng.random()
                status = (Bed.Status.OCCUPIED if roll < 0.62 else Bed.Status.CLEANING if roll < 0.7
                          else Bed.Status.MAINTENANCE if roll < 0.74 else Bed.Status.AVAILABLE)
                if status == Bed.Status.OCCUPIED and not patients:
                    status = Bed.Status.AVAILABLE
                bed = Bed.objects.create(ward=ward, label=f"{n:02d}", status=status)
                if status == Bed.Status.OCCUPIED:
                    admission = Admission.objects.create(patient=patients.pop(), bed=bed,
                                                         reason=self.rng.choice(reasons),
                                                         attending=self.rng.choice(self.doctors))
                    Admission.objects.filter(pk=admission.pk).update(
                        admitted_at=self.now - timedelta(hours=self.rng.randint(3, 140)))
