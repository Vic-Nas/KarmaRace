# accounts/middleware.py
"""Middleware to intercept users who haven't chosen a username yet."""
from django.shortcuts import redirect
from django.urls import reverse

from accounts.views.username import username_needs_picking

# Path segments that are always passthrough regardless of URL prefix.
_PASSTHROUGH_SEGMENTS = (
    '/accounts/',
    '/admin/',
    '/static/',
    '/favicon',
)


class RequireUsernameMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._pick_url = None

    def __call__(self, request):
        if self._pick_url is None:
            self._pick_url = reverse('pick_username')

        path = request.path
        if (
            request.user.is_authenticated
            and path != self._pick_url
            and not any(seg in path for seg in _PASSTHROUGH_SEGMENTS)
            and username_needs_picking(request.user)
        ):
            return redirect(self._pick_url)
        return self.get_response(request)