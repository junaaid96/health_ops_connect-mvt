from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*checks):
    """Allow the view only for users passing one of the checks, e.g.
    ``@role_required("is_doctor")`` or ``@role_required("is_ops", "is_doctor")``."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not any(getattr(request.user, check, False) for check in checks):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


patient_required = role_required("is_patient")
doctor_required = role_required("is_doctor")
ops_required = role_required("is_ops")
clinician_required = role_required("is_doctor", "is_ops")
