from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Lets people sign in with either their email address or username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()
        if user is None:
            # Run the hasher anyway to keep response timing uniform.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
