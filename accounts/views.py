from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.utils import redirect_back

from .forms import (
    DoctorApplicationForm,
    LoginForm,
    ProfileForm,
    SignupForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
)
from .models import Notification, User

VERIFY_SALT = "accounts.verify-email"


def send_verification_email(user):
    token = signing.dumps({"u": user.pk, "e": user.email}, salt=VERIFY_SALT)
    url = settings.SITE_URL + reverse("accounts:verify_email", args=[token])
    send_mail(
        f"Confirm your email · {settings.SITE_NAME}",
        f"Hi {user.first_name},\n\nConfirm your email address to receive appointment updates:\n{url}\n\n"
        "The link is valid for 3 days.",
        None,
        [user.email],
        fail_silently=True,
    )


def _redirect_authenticated(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return None


def signup(request):
    if response := _redirect_authenticated(request):
        return response
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
        send_verification_email(user)
        messages.success(request, f"Welcome, {user.first_name}! Complete your health passport so doctors have what they need.")
        next_url = request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
            return redirect(next_url)
        return redirect("records:health")
    return render(request, "accounts/signup.html", {"form": form})


def doctor_apply(request):
    if response := _redirect_authenticated(request):
        return response
    form = DoctorApplicationForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
        send_verification_email(user)
        for ops in User.objects.filter(role=User.Role.STAFF, is_active=True):
            from core.notify import notify

            notify(ops, "New doctor application", f"{user.display_name} · {user.doctor.specialty}",
                   reverse("operations:doctors"), kind="info")
        messages.success(request, "Application received. Set up your weekly schedule while we verify your licence.")
        return redirect("clinic:schedule")
    return render(request, "accounts/doctor_apply.html", {"form": form})


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


def verify_email(request, token):
    try:
        data = signing.loads(token, salt=VERIFY_SALT, max_age=60 * 60 * 24 * 3)
        user = User.objects.get(pk=data["u"], email=data["e"])
    except (signing.BadSignature, User.DoesNotExist, KeyError):
        messages.error(request, "That verification link is invalid or has expired.")
        return redirect("core:home")
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    messages.success(request, "Email confirmed — you'll now get appointment updates by email.")
    return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")


@login_required
@require_POST
def resend_verification(request):
    send_verification_email(request.user)
    messages.info(request, f"We sent a new confirmation link to {request.user.email}.")
    return redirect_back(request, "core:dashboard")


@login_required
def account_settings(request):
    old_email = request.user.email
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        if user.email != old_email:
            user.email_verified = False
        user.save()
        if not user.email_verified:
            send_verification_email(user)
        messages.success(request, "Profile saved.")
        return redirect("accounts:settings")
    return render(request, "accounts/settings.html", {"form": form})


@login_required
def notifications(request):
    items = request.user.notifications.all()[:100]
    return render(request, "accounts/notifications.html", {"items": items})


@login_required
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    if not note.is_read:
        note.is_read = True
        note.save(update_fields=["is_read"])
    target = note.url if note.url and url_has_allowed_host_and_scheme(note.url, {request.get_host()}) else None
    return redirect(target or "accounts:notifications")


@login_required
@require_POST
def notifications_read_all(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect("accounts:notifications")


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = StyledPasswordResetForm
    email_template_name = "accounts/email/password_reset.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
    extra_email_context = {"site_url": settings.SITE_URL}


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy("accounts:login")

    def form_valid(self, form):
        messages.success(self.request, "Password updated. You can sign in now.")
        return super().form_valid(form)
