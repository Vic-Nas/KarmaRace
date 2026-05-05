# setup/honeypot/payload.py
"""Lazy-rendered honeypot payload (help page)."""

import logging
from functools import lru_cache

from django.http import StreamingHttpResponse
import asyncio

logger = logging.getLogger(__name__)

STREAM_CHUNK = 256
STREAM_DELAY = 2.0


@lru_cache(maxsize=1)
def _get_payload() -> bytes:
    """Render the help page to bytes on first call, cache forever."""
    try:
        from django.test import RequestFactory
        from django.template.loader import render_to_string
        from django.contrib.auth.models import AnonymousUser
        rf = RequestFactory()
        request = rf.get("/help/")
        request.user = AnonymousUser()
        html = render_to_string("help/index.html", request=request)
        return html.encode("utf-8")
    except Exception as exc:
        logger.warning("honeypot: could not render help page: %s", exc)
        return b""


def _tarpit_response() -> StreamingHttpResponse:
    payload = _get_payload()

    async def _gen():
        for i in range(0, len(payload), STREAM_CHUNK):
            yield payload[i : i + STREAM_CHUNK]
            await asyncio.sleep(STREAM_DELAY)

    resp = StreamingHttpResponse(_gen(), status=200, content_type="text/html; charset=utf-8")
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
