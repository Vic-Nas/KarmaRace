# notifications/services.py
import logging

from notifications.models import Notification, NotificationPreference

logger = logging.getLogger(__name__)


def notify(user, event, payload: dict):
    """
    Central notification dispatch.

    1. Always writes a Notification row for in-app display.
    2. If the user is Pro and has a NotificationPreference for this event:
       - email_enabled → queues a procrastinate email delivery task.
       - webhook_url   → queues a procrastinate webhook delivery task.
    """
    notification = Notification.objects.create(
        user=user,
        event=event,
        payload=payload,
    )

    if not user.is_pro:
        return notification

    try:
        pref = NotificationPreference.objects.get(user=user, event=event)
    except NotificationPreference.DoesNotExist:
        return notification

    if pref.email_enabled:
        _queue_email_delivery(pref, payload)

    if pref.webhook_url:
        _queue_webhook_delivery(pref, payload)

    return notification


def _queue_email_delivery(pref, payload: dict):
    try:
        from notifications.tasks import deliver_notification_email
        deliver_notification_email.defer(preference_id=pref.pk, payload=payload)
    except Exception as exc:
        logger.error(
            'notify: failed to queue email delivery for preference %s: %s',
            pref.pk, exc,
        )


def _queue_webhook_delivery(pref, payload: dict):
    try:
        from notifications.tasks import deliver_notification_webhook
        deliver_notification_webhook.defer(preference_id=pref.pk, payload=payload)
    except Exception as exc:
        logger.error(
            'notify: failed to queue webhook delivery for preference %s: %s',
            pref.pk, exc,
        )