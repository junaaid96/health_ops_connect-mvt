"""Rule-based symptom triage.

Deliberately simple and explainable: every suggestion comes with the exact
words that triggered it, so patients (and clinicians) can see *why*. It
routes people to the right specialty and flags emergencies; it does not
diagnose.
"""

import re
from dataclasses import dataclass, field

from appointments.models import Urgency

# Specialty slug -> keywords/phrases that point to it.
SPECIALTY_RULES = {
    "general-medicine": [
        "fever", "cold", "flu", "cough", "fatigue", "tired", "weakness", "body ache", "sore throat",
        "check up", "checkup", "infection", "vomiting", "weight loss", "chills",
    ],
    "cardiology": [
        "chest pain", "chest tightness", "palpitation", "heart", "high blood pressure", "hypertension",
        "irregular heartbeat", "shortness of breath on exertion", "swollen ankles", "cholesterol",
    ],
    "dermatology": [
        "rash", "itch", "itching", "acne", "pimple", "eczema", "skin", "hair loss", "mole", "psoriasis",
        "hives", "dandruff", "nail",
    ],
    "pediatrics": [
        "child", "baby", "infant", "toddler", "my son", "my daughter", "kid", "vaccination", "newborn",
    ],
    "orthopedics": [
        "back pain", "joint pain", "knee", "shoulder", "fracture", "sprain", "neck pain", "hip",
        "bone", "ankle", "arthritis", "sports injury", "muscle pain",
    ],
    "neurology": [
        "headache", "migraine", "dizziness", "dizzy", "numbness", "tingling", "seizure", "memory",
        "tremor", "fainting", "vertigo",
    ],
    "gastroenterology": [
        "stomach", "abdominal pain", "diarrhea", "diarrhoea", "constipation", "acidity", "heartburn",
        "bloating", "nausea", "indigestion", "gastric", "ulcer", "jaundice",
    ],
    "ent": [
        "ear", "earache", "hearing", "sinus", "nose", "nosebleed", "tonsil", "throat", "snoring",
        "blocked nose", "voice",
    ],
    "gynecology": [
        "period", "menstrual", "pregnan", "pcos", "pelvic pain", "vaginal", "fertility",
        "menopause", "breast",
    ],
    "psychiatry": [
        "anxiety", "anxious", "depress", "stress", "panic", "insomnia", "can't sleep", "cannot sleep",
        "mood", "sad", "burnout", "addiction",
    ],
    "ophthalmology": [
        "eye", "vision", "blurry", "blurred", "red eye", "watery eyes", "glasses", "cataract",
    ],
    "endocrinology": [
        "diabetes", "sugar", "thyroid", "glucose", "hormone", "excessive thirst", "frequent urination",
    ],
    "pulmonology": [
        "asthma", "wheez", "breathing", "breathless", "shortness of breath", "chronic cough", "copd",
        "lung", "phlegm",
    ],
}

# Phrases that warrant emergency care rather than a clinic booking.
RED_FLAGS = [
    (["chest pain", "chest pressure", "crushing chest"], "Chest pain can signal a heart attack."),
    (["can't breathe", "cannot breathe", "difficulty breathing", "struggling to breathe", "severe shortness of breath"],
     "Severe breathing difficulty needs immediate care."),
    (["face drooping", "slurred speech", "arm weakness", "one side weak", "stroke"],
     "These can be signs of a stroke — every minute matters."),
    (["unconscious", "passed out", "unresponsive", "seizure"], "Loss of consciousness or seizures need urgent assessment."),
    (["severe bleeding", "bleeding heavily", "won't stop bleeding", "vomiting blood", "coughing blood"],
     "Heavy or internal bleeding needs emergency care."),
    (["suicid", "kill myself", "end my life", "self harm", "self-harm"],
     "You deserve support right now. Please contact emergency services or a crisis line."),
    (["worst headache", "thunderclap"], "A sudden, severe headache needs emergency evaluation."),
    (["severe allergic", "throat closing", "anaphylaxis", "swollen tongue"], "Possible anaphylaxis — use an EpiPen if you have one."),
]

SEVERITY_URGENT = 8
SEVERITY_SOON = 5


@dataclass
class SpecialtyMatch:
    slug: str
    score: float
    matched: list = field(default_factory=list)


@dataclass
class TriageResult:
    text: str
    matches: list
    red_flags: list
    urgency: int

    @property
    def is_emergency(self):
        return bool(self.red_flags)

    @property
    def top_slugs(self):
        return [m.slug for m in self.matches]

    @property
    def urgency_label(self):
        return Urgency(self.urgency).label


def _normalise(text):
    return re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()


def _contains(haystack, needle):
    # Word-boundary match at the start so "ear" doesn't match "heart" or
    # "year", while prefixes like "depress" still catch "depression". Short
    # words must match whole (plural allowed) so "kid" doesn't hit "kidney".
    pattern = r"(?<![a-z])" + re.escape(needle)
    if len(needle) <= 4:
        pattern += r"s?(?![a-z])"
    return re.search(pattern, haystack) is not None


def analyze(text, severity=None, duration=None, limit=3):
    """Analyse free-text symptoms. Returns ranked specialties, red flags and
    an urgency level derived from red flags + self-reported severity."""
    t = _normalise(text)
    matches = []
    for slug, keywords in SPECIALTY_RULES.items():
        hits = [k for k in keywords if _contains(t, k)]
        if hits:
            # Multi-word phrases are more specific, so weigh them higher.
            score = sum(1 + 0.5 * k.count(" ") for k in hits)
            matches.append(SpecialtyMatch(slug, score, hits))
    matches.sort(key=lambda m: (-m.score, m.slug))
    if not matches and t:
        matches = [SpecialtyMatch("general-medicine", 0.1, [])]

    red = []
    for phrases, message in RED_FLAGS:
        hit = next((p for p in phrases if _contains(t, p)), None)
        if hit:
            red.append({"phrase": hit, "message": message})

    urgency = Urgency.ROUTINE
    sev = int(severity) if severity not in (None, "") else None
    if red or (sev is not None and sev >= SEVERITY_URGENT):
        urgency = Urgency.URGENT
    elif (sev is not None and sev >= SEVERITY_SOON) or duration == "hours":
        urgency = Urgency.SOON
    return TriageResult(text=text or "", matches=matches[:limit], red_flags=red, urgency=int(urgency))
