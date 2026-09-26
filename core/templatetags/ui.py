"""Small presentation helpers: inline Lucide icons, badges, money."""

from functools import lru_cache
from pathlib import Path

from django import template
from django.conf import settings
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()
ICON_DIR = Path(__file__).resolve().parent.parent / "icons"


@lru_cache(maxsize=256)
def _icon_body(name):
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        path = ICON_DIR / "circle.svg"
    svg = path.read_text()
    start, end = svg.index(">", svg.index("<svg")) + 1, svg.rindex("</svg>")
    return svg[start:end].strip()


@register.simple_tag
def icon(name, css="size-5", stroke="2", label=""):
    """Inline a Lucide icon: {% icon "calendar" "size-4 text-brand-600" %}."""
    aria = format_html('role="img" aria-label="{}"', label) if label else mark_safe('aria-hidden="true"')
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="{}" stroke-linecap="round" stroke-linejoin="round" class="{} shrink-0" {}>{}</svg>',
        stroke, css, aria, mark_safe(_icon_body(name)),
    )


STATUS_STYLES = {
    "booked": ("badge-sky", "calendar-check"),
    "checked_in": ("badge-violet", "map-pin-check"),
    "in_progress": ("badge-amber", "stethoscope"),
    "completed": ("badge-emerald", "circle-check"),
    "cancelled": ("badge-slate", "circle-x"),
    "no_show": ("badge-rose", "user-x"),
}


@register.inclusion_tag("components/status_badge.html")
def status_badge(appt):
    css, ico = STATUS_STYLES.get(appt.status, ("badge-slate", "circle"))
    return {"css": css, "icon": ico, "label": appt.get_status_display()}


URGENCY_STYLES = {1: ("badge-emerald", "leaf"), 2: ("badge-amber", "clock-alert"), 3: ("badge-rose", "siren")}


@register.inclusion_tag("components/status_badge.html")
def urgency_badge(level, label=None):
    from appointments.models import Urgency

    css, ico = URGENCY_STYLES.get(int(level), URGENCY_STYLES[1])
    return {"css": css, "icon": ico, "label": label or Urgency(int(level)).label}


@register.filter
def money(value):
    if value in (None, ""):
        return ""
    amount = f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{settings.CURRENCY_SYMBOL}{amount}"


@register.filter
def stars(value):
    """Rounded 0–5 star count for display."""
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.simple_tag(takes_context=True)
def active(context, *prefixes):
    """'is-active' when the current path starts with any prefix."""
    request = context.get("request")
    if request is None:
        return ""
    path = request.path
    return "is-active" if any(path.startswith(p) for p in prefixes) else ""


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    query = context["request"].GET.copy() if context.get("request") else {}
    for key, value in kwargs.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


@register.filter
def open_slots(slots):
    return sum(1 for s in slots if s.is_open)
