from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("join-as-doctor/", views.doctor_apply, name="doctor_apply"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("verify/<str:token>/", views.verify_email, name="verify_email"),
    path("verify-resend/", views.resend_verification, name="resend_verification"),
    path("settings/", views.account_settings, name="settings"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/<int:pk>/", views.notification_open, name="notification_open"),
    path("notifications/read-all/", views.notifications_read_all, name="notifications_read_all"),
    path("password-reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
]
