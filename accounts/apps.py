# accounts/apps.py

from django.apps import AppConfig
from django.db.models.signals import post_migrate


def ensure_site_config(sender, **kwargs):
    from django.conf import settings
    from django.contrib.sites.models import Site

    site_id = getattr(settings, "SITE_ID", None)
    domain = getattr(settings, "DOMAIN", "")
    if not site_id or not domain:
        return

    try:
        Site.objects.update_or_create(
            id=site_id,
            defaults={"domain": domain, "name": domain},
        )
    except Exception:
        # Skip if DB tables are not ready yet.
        pass

class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        import accounts.signals          # noqa: F401
        import accounts.outreach.tasks   # noqa: F401  registers @app.periodic tasks with Procrastinate

        post_migrate.connect(
            ensure_site_config,
            dispatch_uid="accounts.ensure_site_config",
        )