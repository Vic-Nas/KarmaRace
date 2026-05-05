# setup/honeypot/trie.py
"""URL trie: build, insert, and walk."""

from dataclasses import dataclass, field
from functools import lru_cache

_WILDCARD = "<*>"   # sentinel for any parameterised segment


@dataclass
class _Node:
    children: dict = field(default_factory=dict)
    is_terminal: bool = False


def _build_trie() -> _Node:
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
    from django.urls.resolvers import RoutePattern
    if not isinstance(pattern, RoutePattern):
        return []
    raw = str(pattern).rstrip("/")
    if not raw:
        return []
    parts = [p for p in raw.split("/") if p]
    return [_WILDCARD if p.startswith("<") else p for p in parts]


def _insert_open_wildcard(root: _Node, prefix: list) -> None:
    node = root
    for seg in prefix:
        if seg not in node.children:
            node.children[seg] = _Node()
        node = node.children[seg]
    wildcard_node = _Node(is_terminal=True)
    wildcard_node.children[_WILDCARD] = wildcard_node
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
