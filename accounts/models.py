# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    is_pro = models.BooleanField(default=False)


class LinkedAccount(models.Model):
    GITHUB      = 'github'
    PRODUCTHUNT = 'producthunt'
    DISCORD     = 'discord'
    PLATFORM_CHOICES = [
        (GITHUB,      'GitHub'),
        (PRODUCTHUNT, 'Product Hunt'),
        (DISCORD,     'Discord'),
    ]

    user              = models.ForeignKey(User, on_delete=models.CASCADE, related_name='linked_accounts')
    platform          = models.CharField(max_length=50, choices=PLATFORM_CHOICES)
    platform_id       = models.CharField(max_length=200)
    platform_username = models.CharField(max_length=200)
    access_token      = models.CharField(max_length=500, blank=True)
    connected_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'platform'), ('platform', 'platform_id')]

    # NOTE: WebhookSubscription and WebhookDelivery have been moved to the
    # notifications app as NotificationPreference and NotificationDelivery.
    # Remove the migration for those models from accounts once the notifications
    # app migration is confirmed live.


class UserPreference(models.Model):
    """
    Per-user overrides for platform defaults.
    Lookup pattern: check here first, fall back to setup/platform_rules.py if absent.
    """
    user  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='preferences')
    key   = models.CharField(max_length=100)
    value = models.CharField(max_length=500)

    class Meta:
        unique_together = [('user', 'key')]

    def __str__(self):
        return f'{self.user_id} / {self.key} = {self.value}'