# notifications/tasks.py
import logging
import requests

from procrastinate.contrib.django import app

from notifications.models import NotificationPreference, NotificationDelivery

logger = logging.getLogger(__name__)

EVENT_LABELS = {
    'TASK_CONFIRMED':     '✅ Task Confirmed',
    'TASK_HEALTH_FAILED': '⚠️ Task Health Failed',
    'WEBHOOK_CHECK':      '🔗 Webhook Check',
    'KARMA_LOW':          '📉 Karma Low',
    'KARMA_RESTORED':     '📈 Karma Restored',
    'KARMA_ADJUSTED':     '⚖️ Karma Adjusted',
    'PROJECT_STATE':      '📌 Project Update',
    'APPRECIATION':       '❤️ Appreciation',
    'FLAG_UP_RECEIVED':   '🚩 Flag Received',
    'FLAG_UP_SENT':       '🚩 Flag Sent',
}


def _build_discord_message(event, payload, label):
    lines = [f'**{label}**']
    if event == 'KARMA_ADJUSTED':
        delta = payload.get('delta', 0)
        sign = '+' if delta >= 0 else ''
        lines.append(f'Amount: **{sign}{delta}**')
        if payload.get('new_balance') is not None:
            lines.append(f'New balance: **{payload["new_balance"]}**')
        if payload.get('reason'):
            lines.append(f'Reason: {payload["reason"]}')
    elif event == 'TASK_HEALTH_FAILED':
        lines.append(f'Task #{payload.get("task_id", "?")}')
        if payload.get('health_last_failure_reason'):
            lines.append(f'Reason: {payload["health_last_failure_reason"]}')
    elif event == 'WEBHOOK_CHECK':
        phase = payload.get('phase', '')
        status = payload.get('status', '')
        lines.append(f'Task #{payload.get("task_id", "?")} — {phase} -> `{status}`')
        if payload.get('tester_username'):
            lines.append(f'Tester: {payload["tester_username"]}')
        if payload.get('detail'):
            lines.append(f'Detail: {payload["detail"]}')
    elif event in ('KARMA_LOW', 'KARMA_RESTORED'):
        lines.append(f'Balance: **{payload.get("balance", "?")}** (threshold {payload.get("threshold", "?")})')
    else:
        if payload.get('task_id'):
            lines.append(f'Task #{payload["task_id"]}')
        if payload.get('balance') is not None:
            lines.append(f'Karma balance: **{payload["balance"]}**')
        if payload.get('status'):
            lines.append(f'Status: `{payload["status"]}`')
    return '\n'.join(lines)


def _retry_or_log(task_fn, preference_id, payload, attempt, max_attempts):
    if attempt < max_attempts:
        try:
            task_fn.defer(preference_id=preference_id, payload=payload,
                          attempt=attempt + 1, max_attempts=max_attempts)
        except Exception as defer_exc:
            logger.error('retry enqueue failed for preference %s: %s', preference_id, defer_exc)


@app.task
def deliver_notification_webhook(preference_id: int, payload: dict, attempt: int = 1, max_attempts: int = 3):
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
        logger.error('deliver_notification_webhook: attempt %s/%s failed for preference %s: %s',
                     attempt, max_attempts, preference_id, exc)
        _retry_or_log(deliver_notification_webhook, preference_id, payload, attempt, max_attempts)

    NotificationDelivery.objects.create(
        preference=pref, channel=NotificationDelivery.Channel.WEBHOOK,
        payload=payload, state=state, attempts=attempt,
    )


@app.task
def deliver_notification_discord(preference_id: int, payload: dict, attempt: int = 1, max_attempts: int = 3):
    try:
        pref = NotificationPreference.objects.select_related('user').get(pk=preference_id)
    except NotificationPreference.DoesNotExist:
        logger.error('deliver_notification_discord: preference %s not found', preference_id)
        return

    from accounts.models import LinkedAccount
    discord_link = LinkedAccount.objects.filter(
        user=pref.user, platform=LinkedAccount.DISCORD,
    ).first()

    if not discord_link:
        logger.info('deliver_notification_discord: user %s has no linked Discord', pref.user_id)
        NotificationDelivery.objects.create(
            preference=pref, channel=NotificationDelivery.Channel.DISCORD,
            payload=payload, state=NotificationDelivery.State.FAILED, attempts=attempt,
        )
        return

    state = NotificationDelivery.State.FAILED
    try:
        from accounts import discord as discord_api

        label = EVENT_LABELS.get(pref.event, pref.event)
        message = _build_discord_message(pref.event, payload, label)

        dm_resp = requests.post(
            f'{discord_api.DISCORD_API_BASE}/users/@me/channels',
            headers=discord_api._bot_headers(),
            json={'recipient_id': discord_link.platform_id},
            timeout=10,
        )
        dm_resp.raise_for_status()
        channel_id = dm_resp.json()['id']

        msg_resp = requests.post(
            f'{discord_api.DISCORD_API_BASE}/channels/{channel_id}/messages',
            headers=discord_api._bot_headers(),
            json={'content': message},
            timeout=10,
        )
        msg_resp.raise_for_status()
        state = NotificationDelivery.State.SUCCESS

    except Exception as exc:
        logger.error('deliver_notification_discord: attempt %s/%s failed for preference %s: %s',
                     attempt, max_attempts, preference_id, exc)
        _retry_or_log(deliver_notification_discord, preference_id, payload, attempt, max_attempts)

    NotificationDelivery.objects.create(
        preference=pref, channel=NotificationDelivery.Channel.DISCORD,
        payload=payload, state=state, attempts=attempt,
    )