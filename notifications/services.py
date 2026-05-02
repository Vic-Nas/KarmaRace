# notifications/services.py
import logging

from notifications.models import Notification, NotificationPreference

logger = logging.getLogger(__name__)


EVENTS_BYPASS_PRO_GATE = {
    'WEBHOOK_CHECK',
    'TASK_HEALTH_FAILED',
}


def notify(user, event, payload: dict):
    """
    Central notification dispatch.

    1. Always writes a Notification row for in-app display.
    2. If the user is Pro (or the event bypasses the Pro gate) and has a
       NotificationPreference for this event, dispatches to enabled channels:
       webhook, discord.
    """
    notification = Notification.objects.create(user=user, event=event, payload=payload)

    if not user.is_pro and event not in EVENTS_BYPASS_PRO_GATE:
        return notification

    try:
        pref = NotificationPreference.objects.get(user=user, event=event)
    except NotificationPreference.DoesNotExist:
        return notification

    if pref.webhook_url:
        _queue_delivery('webhook', pref, payload)

    if pref.discord_enabled:
        _queue_delivery('discord', pref, payload)

    return notification


def _queue_delivery(channel: str, pref, payload: dict):
    """Queue a delivery task, falling back to synchronous execution on queue failure."""
    from notifications import tasks as notif_tasks

    task_fn = {
        'webhook': notif_tasks.deliver_notification_webhook,
        'discord': notif_tasks.deliver_notification_discord,
    }.get(channel)

    if task_fn is None:
        return

    try:
        task_fn.defer(preference_id=pref.pk, payload=payload, attempt=1, max_attempts=3)
    except Exception as exc:
        logger.error('notify: failed to queue %s delivery for preference %s: %s', channel, pref.pk, exc)
        try:
            task_fn(preference_id=pref.pk, payload=payload, attempt=1, max_attempts=1)
        except Exception as fallback_exc:
            logger.error('notify: fallback %s delivery failed for preference %s: %s',
                         channel, pref.pk, fallback_exc)
