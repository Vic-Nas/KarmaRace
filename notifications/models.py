# notifications/models.py
from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Event(models.TextChoices):
        TASK_CONFIRMED     = 'TASK_CONFIRMED'
        TASK_HEALTH_FAILED = 'TASK_HEALTH_FAILED'
        KARMA_LOW          = 'KARMA_LOW'
        PROJECT_STATE      = 'PROJECT_STATE'
        APPRECIATION       = 'APPRECIATION'
        FLAG_UP_RECEIVED   = 'FLAG_UP_RECEIVED'
        FLAG_UP_SENT       = 'FLAG_UP_SENT'

    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    event      = models.CharField(max_length=30, choices=Event.choices)
    payload    = models.JSONField()
    read_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class NotificationPreference(models.Model):
    user          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_preferences')
    event         = models.CharField(max_length=30, choices=Notification.Event.choices)
    email_enabled = models.BooleanField(default=False)
    webhook_url   = models.URLField(blank=True)

    class Meta:
        unique_together = [('user', 'event')]


class NotificationDelivery(models.Model):
    class Channel(models.TextChoices):
        EMAIL   = 'EMAIL'
        WEBHOOK = 'WEBHOOK'

    class State(models.TextChoices):
        SUCCESS = 'SUCCESS'
        FAILED  = 'FAILED'

    preference = models.ForeignKey(NotificationPreference, on_delete=models.CASCADE, related_name='deliveries')
    channel    = models.CharField(max_length=10, choices=Channel.choices)
    payload    = models.JSONField()
    state      = models.CharField(max_length=10, choices=State.choices)
    attempts   = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)