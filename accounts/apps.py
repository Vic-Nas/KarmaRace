# accounts/apps.py

from django.apps import AppConfig
from django.core.checks import Warning, register
from django.db.models.signals import post_migrate


REQUIRED_PLATFORM_CONFIG_KEYS = [
    'karma_reward_github_star',
    'karma_reward_github_fork',
    'karma_reward_ph',
    'karma_reward_webhook',
    'karma_low_threshold',
]


@register()
def check_required_platform_configs(app_configs, **kwargs):
    """Warn when required PlatformConfig keys are missing."""
    from django.db.utils import OperationalError, ProgrammingError

    from accounts.models import PlatformConfig

    try:
        existing = set(
            PlatformConfig.objects.filter(key__in=REQUIRED_PLATFORM_CONFIG_KEYS)
            .values_list('key', flat=True)
        )
    except (OperationalError, ProgrammingError):
        # DB or table may not exist yet during early startup/migrate.
        return []

    missing = [key for key in REQUIRED_PLATFORM_CONFIG_KEYS if key not in existing]
    if not missing:
        return []

    return [
        Warning(
            'Missing required PlatformConfig keys: ' + ', '.join(missing),
            hint='Create missing keys in admin under PlatformConfig.',
            id='accounts.W001',
        )
    ]


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
        post_migrate.connect(
            ensure_site_config,
            dispatch_uid="accounts.ensure_site_config",
        )
