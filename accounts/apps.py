# accounts/apps.py

from django.apps import AppConfig

class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        from django.contrib.sites.models import Site
        from django.conf import settings
        try:
            Site.objects.update_or_create(
                id=settings.SITE_ID,
                defaults={'domain': settings.DOMAIN, 'name': settings.DOMAIN}
            )
        except Exception:
            pass  # DB not ready yet (e.g. pre-migrate)