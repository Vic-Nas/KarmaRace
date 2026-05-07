# setup/honeypot/middleware.py
"""HoneypotMiddleware — async-only tarpit + redirect for broken paths."""

import inspect
import logging

from asgiref.sync import markcoroutinefunction
from django.contrib import messages
from django.shortcuts import redirect

from .classify import _classify, _HONEYPOT, _REAL_404
from .payload import _tarpit_response

logger = logging.getLogger(__name__)


class HoneypotMiddleware:
    """
    Async-only middleware. Must sit after MessageMiddleware in settings.MIDDLEWARE:

        'django.contrib.messages.middleware.MessageMiddleware',
        'setup.honeypot.HoneypotMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware',

    sync_capable = False causes Django to raise ImproperlyConfigured at startup
    if placed in a WSGI stack — no silent fallback to blocking behaviour.
    """

    async_capable = True
    sync_capable  = False

    def __init__(self, get_response):
        if not inspect.iscoroutinefunction(get_response):
            raise RuntimeError(
                "HoneypotMiddleware requires ASGI (uvicorn/daphne). "
                "sync_capable=False — do not deploy under WSGI."
            )
        self.get_response = get_response
        markcoroutinefunction(self)

    async def __call__(self, request):
        verdict, redirect_path = _classify(request.path)

        if verdict == _REAL_404:
            logger.warning(
                "broken_path: path=%s ua=%s",
                request.path,
                request.META.get("HTTP_USER_AGENT", "")[:120],
            )
            messages.info(
                request,
                f"\"{request.path}\" isn't a known page => redirecting you to {redirect_path}.",
            )
            return redirect(redirect_path, permanent=False)

        if verdict == _HONEYPOT:
            logger.debug(
                "honeypot: path=%s ua=%s",
                request.path,
                request.META.get("HTTP_USER_AGENT", "")[:120],
            )
            return _tarpit_response()

        return await self.get_response(request)
