# setup/apps.py
from django.apps import AppConfig


class SetupConfig(AppConfig):
    name = "setup"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Do NOT touch the URL resolver or render templates here.
        # Both the trie and the honeypot payload are built lazily on the
        # first request, which is always after full app initialization.
        pass