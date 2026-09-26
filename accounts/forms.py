import secrets

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm, UserCreationForm
from django.db import transaction
from django.utils.text import slugify

from clinic.models import Doctor, Specialty
from core.forms import StyledFormMixin
from records.models import HealthProfile

from .models import User


def _unique_username(email):
    base = slugify(email.split("@")[0])[:20] or "user"
    candidate = base
    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f"{base}{secrets.randbelow(9000) + 1000}"
    return candidate


class LoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.CharField(label="Email or username", widget=forms.TextInput(attrs={
        "autofocus": True, "autocomplete": "username", "placeholder": "you@example.com"}))
    password = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={
        "autocomplete": "current-password", "placeholder": "••••••••"}))


class SignupForm(StyledFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=50, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(max_length=50, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@example.com"}))
    phone = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={
        "autocomplete": "tel", "inputmode": "tel", "placeholder": "Optional — for appointment reminders"}))

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Try signing in instead.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = _unique_username(user.email)
        user.role = User.Role.PATIENT
        if commit:
            with transaction.atomic():
                user.save()
                HealthProfile.objects.create(user=user)
        return user


class DoctorApplicationForm(SignupForm):
    """Doctors sign up, but aren't listed until operations staff verify
    their licence."""

    specialty = forms.ModelChoiceField(queryset=Specialty.objects.all(), empty_label="Choose your specialty")
    title = forms.CharField(max_length=80, initial="Consultant")
    qualifications = forms.CharField(max_length=160, widget=forms.TextInput(attrs={"placeholder": "MBBS, FCPS (Medicine)"}))
    license_number = forms.CharField(max_length=40, label="Medical licence / registration number")
    years_experience = forms.IntegerField(min_value=0, max_value=70, initial=5)
    fee = forms.DecimalField(min_value=0, max_digits=8, decimal_places=2, label="Consultation fee")
    languages = forms.CharField(max_length=120, initial="English", help_text="Comma separated")
    bio = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), required=False)
    photo = forms.ImageField(required=False, help_text="A clear, professional headshot")
    offers_in_person = forms.BooleanField(required=False, initial=True, label="In-person visits")
    offers_video = forms.BooleanField(required=False, initial=True, label="Video visits")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("offers_in_person") and not cleaned.get("offers_video"):
            raise forms.ValidationError("Offer at least one visit type (in-person or video).")
        return cleaned

    def save(self, commit=True):
        user = UserCreationForm.save(self, commit=False)
        user.username = _unique_username(user.email)
        user.role = User.Role.DOCTOR
        with transaction.atomic():
            user.save()
            data = self.cleaned_data
            Doctor.objects.create(
                user=user,
                specialty=data["specialty"],
                title=data["title"],
                qualifications=data["qualifications"],
                license_number=data["license_number"],
                years_experience=data["years_experience"],
                fee=data["fee"],
                languages=data["languages"],
                bio=data["bio"],
                photo=data.get("photo") or "",
                offers_in_person=data["offers_in_person"],
                offers_video=data["offers_video"],
                is_verified=False,
            )
        return user


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone", "avatar")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account already uses this email.")
        return email


class StyledPasswordResetForm(StyledFormMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(StyledFormMixin, SetPasswordForm):
    pass
