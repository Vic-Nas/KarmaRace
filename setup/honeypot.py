# setup/honeypot.py
"""
Honeypot + tarpit middleware for KarmaRace.

Classification (in order):

  1. Path resolves exactly in the URL trie  → legitimate, pass through.
  2. Path is close to a real route (edit distance ≤ depth + 1 per segment,
     literals preferred over wildcards)     → broken link / typo, real 404
                                              + WARNING so we notice.
  3. Everything else                        → bot/scanner, slow-drip tarpit.

The URL trie is built once at startup by importing Django's root resolver.
No manually-maintained prefix or pattern list exists — the trie is the truth.

Tolerance: depth + 1.  At depth 0 (root) a segment must be within 1 edit of
a real first-level segment to be considered a typo.  The tolerance grows with
depth because a visitor who has navigated several real segments is almost
certainly a human with a plausible typo, not a scanner.

Matching priority per node:
  exact literal → distance check against literals (within tolerance → REAL_404)
               → wildcard (any value matches) → HONEYPOT

ASGI-only: sync_capable=False causes Django to raise at startup if deployed
under WSGI rather than silently falling back to blocking time.sleep, which
would let concurrent bots stall every worker thread.

Under ASGI (uvicorn) asyncio.sleep suspends the coroutine between chunks so
tarpitted bots cost nothing while the event loop serves real users.
"""

import asyncio
import inspect
import logging
import posixpath
import re
import urllib.parse
from dataclasses import dataclass, field
from functools import lru_cache

from asgiref.sync import markcoroutinefunction
from django.http import StreamingHttpResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

STREAM_CHUNK      = 256
STREAM_DELAY      = 2.0    # seconds between chunks — bots wait, event loop stays free
TRIE_DEPTH_CAP    = 5      # beyond this depth all paths are treated as legitimate


# ---------------------------------------------------------------------------
# Levenshtein distance (segment-level: strings are short, simple DP is fine)
# ---------------------------------------------------------------------------

def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j] + (ca != cb), prev[j + 1] + 1, curr[j] + 1))
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# URL trie
# ---------------------------------------------------------------------------

_WILDCARD = "<*>"   # sentinel for any parameterised segment


@dataclass
class _Node:
    children: dict = field(default_factory=dict)
    is_terminal: bool = False


def _build_trie() -> _Node:
    """
    Walk Django's root URL resolver and insert every concrete path into the
    trie.  Parameterised segments (<str:x>, <int:pk>, <slug:s> ...) become
    _WILDCARD nodes so they match any value at runtime.

    Called once, result is cached — safe because URLs don't change at runtime.
    """
    from django.urls import get_resolver
    root = _Node()
    _walk_resolver(get_resolver(), [], root)
    return root


def _walk_resolver(resolver, prefix: list, root: _Node) -> None:
    from django.urls import URLPattern, URLResolver
    from django.urls.resolvers import RoutePattern

    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            segs = _resolver_segments(pattern.pattern)
            new_prefix = prefix + segs
            if not isinstance(pattern.pattern, RoutePattern):
                # Regex-based resolver (e.g. admin, allauth) — we can't
                # walk its internals meaningfully.  Insert a wildcard at
                # this prefix so all sub-paths are treated as legitimate.
                if new_prefix:
                    _insert_open_wildcard(root, new_prefix)
            else:
                _walk_resolver(pattern, new_prefix, root)
        elif isinstance(pattern, URLPattern):
            segs = _resolver_segments(pattern.pattern)
            full = prefix + segs
            if full:
                _insert(root, full)


def _resolver_segments(pattern) -> list:
    """
    Convert a URL pattern component into a list of trie segments.

    Django's RoutePattern str() can contain slashes for multi-segment
    routes like 'notifications/unread/' or 'app/accounts/'.  Split on
    '/' and map each part: empty parts are dropped, '<...>' becomes
    _WILDCARD, literals stay as-is.

    RegexPattern (used by admin and third-party apps) produces raw regex
    strings like '^(?P<app_label>[^/]+)/'.  These are useless for trie
    purposes — skip them entirely so admin internals don't pollute the trie.
    """
    from django.urls.resolvers import RoutePattern
    if not isinstance(pattern, RoutePattern):
        return []
    raw = str(pattern).rstrip("/")
    if not raw:
        return []
    parts = [p for p in raw.split("/") if p]
    return [_WILDCARD if p.startswith("<") else p for p in parts]


def _insert_open_wildcard(root: _Node, prefix: list) -> None:
    """Insert prefix into the trie, then make the final wildcard node
    point to itself — so any depth of sub-path is classified as legitimate.
    Used for regex-based resolvers (admin, allauth) whose internals we
    can't walk but whose entire subtree should be passed through.
    """
    node = root
    for seg in prefix:
        if seg not in node.children:
            node.children[seg] = _Node()
        node = node.children[seg]
    # Create a wildcard child that loops back to itself.
    wildcard_node = _Node(is_terminal=True)
    wildcard_node.children[_WILDCARD] = wildcard_node  # self-referential
    node.children[_WILDCARD] = wildcard_node


def _insert(root: _Node, segments: list) -> None:
    node = root
    for seg in segments:
        if seg not in node.children:
            node.children[seg] = _Node()
        node = node.children[seg]
    node.is_terminal = True


@lru_cache(maxsize=1)
def _trie() -> _Node:
    return _build_trie()


# ---------------------------------------------------------------------------
# Path normalisation
# ---------------------------------------------------------------------------

def _normalize(path: str) -> str:
    """
    Canonicalise before classification:
      //xmlrpc.php          -> /xmlrpc.php
      /%2fxmlrpc.php        -> /xmlrpc.php   (URL-encoded slash)
      /%252fxmlrpc.php      -> /xmlrpc.php   (double-encoded)
      /./wp/../xmlrpc.php   -> /xmlrpc.php   (dot segments)
    Case is preserved; the distance check is case-insensitive.
    """
    decoded = urllib.parse.unquote(urllib.parse.unquote(path))
    decoded = re.sub(r"/+", "/", decoded)
    normalized = posixpath.normpath(decoded)
    if path.endswith("/") and not normalized.endswith("/"):
        normalized += "/"
    return normalized


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_LEGITIMATE = "LEGITIMATE"
_REAL_404   = "REAL_404"
_HONEYPOT   = "HONEYPOT"


def _classify(path: str) -> str:
    # Static files and favicon are served by ServeStatic/WhiteNoise before
    # reaching Django's URL router — they will never appear in the trie.
    # Pass them through explicitly so the middleware doesn't intercept them.
    if path.startswith("/static/") or path == "/favicon.ico":
        return _LEGITIMATE

    if path == "/":
        return _LEGITIMATE

    normalized = _normalize(path)
    segments   = [s for s in normalized.split("/") if s]

    if not segments:
        return _LEGITIMATE

    root = _trie()
    node = root
    matched_depth = 0

    for i, seg in enumerate(segments):

        if i >= TRIE_DEPTH_CAP:
            # Deep enough that we have validated the route structure — legitimate.
            return _LEGITIMATE

        tol = matched_depth + 1   # tolerance grows with confirmed depth

        # 1. Exact literal match — keep walking
        if seg in node.children:
            node = node.children[seg]
            matched_depth += 1
            continue

        # 2. Distance check against literal children (before wildcard fallback)
        literal_keys = [k for k in node.children if k != _WILDCARD]
        if literal_keys:
            best = min(literal_keys, key=lambda k: _lev(seg.lower(), k.lower()))
            dist = _lev(seg.lower(), best.lower())
            if dist <= tol:
                return _REAL_404

        # 3. Wildcard fallback — segment is a user-supplied value
        if _WILDCARD in node.children:
            node = node.children[_WILDCARD]
            matched_depth += 1
            continue

        # 4. Nothing matched and distance too large
        return _HONEYPOT

    return _LEGITIMATE


# ---------------------------------------------------------------------------
# Honeypot payload
#
# Rendered lazily on first honeypot hit — never during app startup — so
# the URL resolver and template engine are fully initialised before we
# touch them.  lru_cache means the render happens exactly once.
# ---------------------------------------------------------------------------

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
    """
    Async streaming response that drip-feeds the help page at STREAM_CHUNK
    bytes every STREAM_DELAY seconds.  Each asyncio.sleep() suspends the
    coroutine and returns control to the event loop — tarpitted bots cost
    zero threads.
    """
    payload = _get_payload()

    async def _gen():
        for i in range(0, len(payload), STREAM_CHUNK):
            yield payload[i : i + STREAM_CHUNK]
            await asyncio.sleep(STREAM_DELAY)

    resp = StreamingHttpResponse(_gen(), status=200, content_type="text/html; charset=utf-8")
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class HoneypotMiddleware:
    """
    Async-only middleware.  Must sit after SecurityMiddleware and
    WhiteNoiseMiddleware in settings.MIDDLEWARE so static files are served
    before classification runs:

        'django.middleware.security.SecurityMiddleware',
        'whitenoise.middleware.WhiteNoiseMiddleware',
        'setup.honeypot.HoneypotMiddleware',      # <- here
        'django.contrib.sessions.middleware.SessionMiddleware',
        ...

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
        verdict = _classify(request.path)

        if verdict == _REAL_404:
            logger.warning(
                "broken_path: path=%s ua=%s",
                request.path,
                request.META.get("HTTP_USER_AGENT", "")[:120],
            )
            return await self.get_response(request)

        if verdict == _HONEYPOT:
            logger.debug(
                "honeypot: path=%s ua=%s",
                request.path,
                request.META.get("HTTP_USER_AGENT", "")[:120],
            )
            return _tarpit_response()

        return await self.get_response(request)