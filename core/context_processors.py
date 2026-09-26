from django.conf import settings


def site(request):
    ctx = {
        "SITE_NAME": settings.SITE_NAME,
        "CURRENCY": settings.CURRENCY_SYMBOL,
        "unread_notifications": 0,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["unread_notifications"] = user.notifications.filter(is_read=False).count()
    return ctx
