import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify(user, title, body="", url="", kind="info", email=False):
    """Create an in-app notification and optionally email it. Email failures
    are logged, never raised — a flaky SMTP server must not break booking."""
    from accounts.models import Notification

    note = Notification.objects.create(user=user, title=title, body=body, url=url, kind=kind)
    if email and user.email:
        link = f"\n\n{settings.SITE_URL}{url}" if url.startswith("/") else ""
        try:
            send_mail(f"{title} · {settings.SITE_NAME}", f"Hi {user.first_name or user.username},\n\n{body}{link}",
                      None, [user.email], fail_silently=False)
        except Exception:  # noqa: BLE001 - any transport error
            logger.exception("Failed to send notification email to user %s", user.pk)
    return note
