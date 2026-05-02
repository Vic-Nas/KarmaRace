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

# Discord embed sidebar colors
EVENT_COLORS = {
    'TASK_CONFIRMED':     0x5cb84a,
    'TASK_HEALTH_FAILED': 0xe06060,
    'WEBHOOK_CHECK':      0x4aaac8,
    'KARMA_LOW':          0xd4b040,
    'KARMA_RESTORED':     0x5cb84a,
    'KARMA_ADJUSTED':     0xe8883a,
    'PROJECT_STATE':      0x888880,
    'APPRECIATION':       0xe06060,
    'FLAG_UP_RECEIVED':   0xe06060,
    'FLAG_UP_SENT':       0x4aaac8,
}


def _build_embed(event, payload, label):
    fields = []

    if event == 'KARMA_ADJUSTED':
        delta = payload.get('delta', 0)
        sign = '+' if delta >= 0 else ''
        fields.append({'name': 'Amount', 'value': f'`{sign}{delta}`', 'inline': True})
        if payload.get('new_balance') is not None:
            fields.append({'name': 'New Balance', 'value': f'`{payload["new_balance"]}`', 'inline': True})
        if payload.get('reason'):
            fields.append({'name': 'Reason', 'value': payload['reason'], 'inline': False})

    elif event == 'TASK_HEALTH_FAILED':
        fields.append({'name': 'Task', 'value': f'#{payload.get("task_id", "?")}', 'inline': True})
        if payload.get('health_last_failure_reason'):
            fields.append({'name': 'Reason', 'value': payload['health_last_failure_reason'], 'inline': False})

    elif event == 'WEBHOOK_CHECK':
        fields.append({'name': 'Task', 'value': f'#{payload.get("task_id", "?")}', 'inline': True})
        fields.append({'name': 'Phase', 'value': payload.get('phase', '—'), 'inline': True})
        fields.append({'name': 'Status', 'value': f'`{payload.get("status", "—")}`', 'inline': True})
        if payload.get('tester_username'):
            fields.append({'name': 'Tester', 'value': payload['tester_username'], 'inline': True})
        if payload.get('detail'):
            fields.append({'name': 'Detail', 'value': payload['detail'], 'inline': False})

    elif event in ('KARMA_LOW', 'KARMA_RESTORED'):
        fields.append({'name': 'Balance', 'value': f'`{payload.get("balance", "?")}`', 'inline': True})
        fields.append({'name': 'Threshold', 'value': f'`{payload.get("threshold", "?")}`', 'inline': True})

    else:
        if payload.get('task_id'):
            fields.append({'name': 'Task', 'value': f'#{payload["task_id"]}', 'inline': True})
        if payload.get('balance') is not None:
            fields.append({'name': 'Balance', 'value': f'`{payload["balance"]}`', 'inline': True})
        if payload.get('status'):
            fields.append({'name': 'Status', 'value': f'`{payload["status"]}`', 'inline': True})

    return {
        'title': label,
        'color': EVENT_COLORS.get(event, 0x888880),
        'fields': fields,
        'footer': {'text': 'KarmaRace'},
    }


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
        embed = _build_embed(pref.event, payload, label)

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
            json={'embeds': [embed]},
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