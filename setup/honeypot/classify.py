# setup/honeypot/classify.py
"""Path normalisation and classification. Returns (verdict, redirect_path | None)."""

import posixpath
import re
import urllib.parse

from .trie import _WILDCARD, _trie

TRIE_DEPTH_CAP = 5

_LEGITIMATE = "LEGITIMATE"
_REAL_404   = "REAL_404"
_HONEYPOT   = "HONEYPOT"


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


def _normalize(path: str) -> str:
    decoded = urllib.parse.unquote(urllib.parse.unquote(path))
    decoded = re.sub(r"/+", "/", decoded)
    normalized = posixpath.normpath(decoded)
    if path.endswith("/") and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def _classify(path: str) -> tuple[str, str | None]:
    """Return (verdict, redirect_path | None).

    - LEGITIMATE → (LEGITIMATE, None)
    - HONEYPOT   → (HONEYPOT, None)
    - REAL_404   → (REAL_404, "/reconstructed/path/")
    """
    if path.startswith("/static/") or path == "/favicon.ico":
        return _LEGITIMATE, None

    if path == "/":
        return _LEGITIMATE, None

    normalized = _normalize(path)
    segments   = [s for s in normalized.split("/") if s]

    if not segments:
        return _LEGITIMATE, None

    root = _trie()
    node = root
    matched_depth = 0
    matched_segments: list[str] = []

    for i, seg in enumerate(segments):

        if i >= TRIE_DEPTH_CAP:
            return _LEGITIMATE, None

        tol = matched_depth + 1

        # 1. Exact literal match
        if seg in node.children:
            node = node.children[seg]
            matched_depth += 1
            matched_segments.append(seg)
            continue

        # 2. Distance check against literals
        literal_keys = [k for k in node.children if k != _WILDCARD]
        if literal_keys:
            best = min(literal_keys, key=lambda k: _lev(seg.lower(), k.lower()))
            dist = _lev(seg.lower(), best.lower())
            if dist <= tol:
                matched_segments.append(best)
                redirect_path = "/" + "/".join(matched_segments) + "/"
                return _REAL_404, redirect_path

        # 3. Wildcard fallback — use the original segment (real user value)
        if _WILDCARD in node.children:
            node = node.children[_WILDCARD]
            matched_depth += 1
            matched_segments.append(seg)
            continue

        # 4. Nothing matched
        return _HONEYPOT, None

    return _LEGITIMATE, None
