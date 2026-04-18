# notifications/tasks.py
import logging
import requests

from procrastinate.contrib.django import app

from notifications.models import Notification, NotificationPreference, NotificationDelivery

logger = logging.getLogger(__name__)


@app.task
def deliver_notification_email(preference_id: int, payload: dict, attempt: int = 1, max_attempts: int = 3):
    """Send an email delivery for a notification preference."""
    from django.conf import settings

    try:
        pref = NotificationPreference.objects.select_related('user').get(pk=preference_id)
    except NotificationPreference.DoesNotExist:
        logger.error('deliver_notification_email: preference %s not found', preference_id)
        return

    state = NotificationDelivery.State.FAILED
    try:
        import resend
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            'from':    settings.RESEND_FROM_EMAIL,
            'to':      pref.user.email,
            'subject': f'Notification: {pref.event}',
            'text':    str(payload),
        })
        state = NotificationDelivery.State.SUCCESS
    except Exception as exc:
        logger.error(
            'deliver_notification_email: attempt %s/%s failed for preference %s: %s',
            attempt, max_attempts, preference_id, exc,
        )
        if attempt < max_attempts:
            try:
                deliver_notification_email.defer(
                    preference_id=preference_id,
                    payload=payload,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                )
            except Exception as defer_exc:
                logger.error(
                    'deliver_notification_email: retry enqueue failed for preference %s: %s',
                    preference_id, defer_exc,
                )

    NotificationDelivery.objects.create(
        preference=pref,
        channel=NotificationDelivery.Channel.EMAIL,
        payload=payload,
        state=state,
        attempts=attempt,
    )


@app.task
def deliver_notification_webhook(preference_id: int, payload: dict, attempt: int = 1, max_attempts: int = 3):
    """POST a webhook delivery for a notification preference."""
    try:
        pref = NotificationPreference.objects.get(pk=preference_id)
    except NotificationPreference.DoesNotExist:
        logger.error('deliver_notification_webhook: preference %s not found', preference_id)
        return

    state = NotificationDelivery.State.FAILED
    try:
        response = requests.post(pref.webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        state = NotificationDelivery.State.SUCCESS
    except Exception as exc:
        logger.error(
            'deliver_notification_webhook: attempt %s/%s failed for preference %s: %s',
            attempt, max_attempts, preference_id, exc,
        )
        if attempt < max_attempts:
            try:
                deliver_notification_webhook.defer(
                    preference_id=preference_id,
                    payload=payload,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                )
            except Exception as defer_exc:
                logger.error(
                    'deliver_notification_webhook: retry enqueue failed for preference %s: %s',
                    preference_id, defer_exc,
                )

    NotificationDelivery.objects.create(
        preference=pref,
        channel=NotificationDelivery.Channel.WEBHOOK,
        payload=payload,
        state=state,
        attempts=attempt,
    )


@app.task
def notify_task_health_failed(task_id: int):
    """Notify a task owner that their task failed a health check."""
    from tasks.models import Task
    from notifications.services import notify

    try:
        task = Task.objects.select_related('owner').get(pk=task_id)
    except Task.DoesNotExist:
        logger.error('notify_task_health_failed: task %s not found', task_id)
        return

    notify(
        user=task.owner,
        event=Notification.Event.TASK_HEALTH_FAILED,
        payload={
            'task_id': task.pk,
            'task_type': task.type,
            'target_id': task.target_id,
            'owner_id': task.owner_id,
        },
    )