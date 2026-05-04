# accounts/middleware.py
"""Middleware to intercept users who haven't chosen a username yet."""
from asgiref.sync import markcoroutinefunction, sync_to_async
from django.shortcuts import redirect
from django.urls import reverse

from accounts.views.username import username_needs_picking

_async_username_needs_picking = sync_to_async(username_needs_picking)

# Path segments that are always passthrough regardless of URL prefix.
_PASSTHROUGH_SEGMENTS = (
    '/accounts/',
    '/admin/',
    '/static/',
    '/favicon',
)


class RequireUsernameMiddleware:
    async_capable = True
    sync_capable = False

    def __init__(self, get_response):
        self.get_response = get_response
        markcoroutinefunction(self)

    async def _should_redirect(self, user, path):
        if not hasattr(self, '_pick_url'):
            self._pick_url = reverse('pick_username')
        return (
            user.is_authenticated
            and path != self._pick_url
            and not any(seg in path for seg in _PASSTHROUGH_SEGMENTS)
            and await _async_username_needs_picking(user)
        )

    async def __call__(self, request):
        user = await request.auser()
        if await self._should_redirect(user, request.path):
            return redirect(self._pick_url)
        return await self.get_response(request)