# setup/apps.py
from django.apps import AppConfig

# Populated in ready() — imported by honeypot.py after Django initialises.
HONEYPOT_PAYLOAD: bytes = b""


class SetupConfig(AppConfig):
    name = "setup"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Do NOT warm the trie here — get_resolver() called during ready()
        # can corrupt the admin namespace if admin.autodiscover() hasn't
        # completed yet (setup is first in INSTALLED_APPS).  The trie builds
        # lazily on the first request instead, which is always post-init.
        _build_honeypot_payload()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_honeypot_payload() -> None:
    """
    Render the help page to a static bytes payload using a fake anonymous
    request.  The result is stored in this module's HONEYPOT_PAYLOAD so
    honeypot.py can stream it without touching the template engine per-request.

    Falls back to an empty payload (honeypot still works, just shorter) if
    rendering fails — e.g. staticfiles manifest not yet present in development.
    """
    global HONEYPOT_PAYLOAD

    try:
        from django.test import RequestFactory
        from django.template.loader import render_to_string
        from django.contrib.auth.models import AnonymousUser

        rf = RequestFactory()
        request = rf.get("/help/")
        request.user = AnonymousUser()

        html = render_to_string(
            "help/index.html",
            request=request,
        )
        HONEYPOT_PAYLOAD = html.encode("utf-8")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "honeypot: could not pre-render help page, using empty payload: %s", exc
        )
        HONEYPOT_PAYLOAD = b""