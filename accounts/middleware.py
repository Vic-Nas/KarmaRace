"""Middleware to intercept users who haven't chosen a username yet."""
from django.shortcuts import redirect
from django.urls import reverse

from accounts.views.username import username_needs_picking

# Paths that must always be accessible regardless of username state.
# Allauth paths, static, admin, and our own pick-username URLs.
_PASSTHROUGH_PREFIXES = (
    '/accounts/',       # allauth + our accounts URLs
    '/admin/',
    '/static/',
    '/favicon',
)


class RequireUsernameMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._pick_url = None

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and not any(request.path.startswith(p) for p in _PASSTHROUGH_PREFIXES)
            and username_needs_picking(request.user)
        ):
            if self._pick_url is None:
                self._pick_url = reverse('pick_username')
            return redirect(self._pick_url)
        return self.get_response(request)
