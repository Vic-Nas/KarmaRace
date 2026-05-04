# notifications/tasks.py
import logging
import requests

import discord

from procrastinate.contrib.django import app

from notifications.models import NotificationPreference, NotificationDelivery

logger = logging.getLogger(__name__)

EVENT_META = {
    'TASK_CONFIRMED':     ('✅ Task Confirmed', 0x5cb84a),
    'TASK_HEALTH_FAILED': ('⚠️ Task Health Failed', 0xe06060),
    'WEBHOOK_CHECK':      ('🔗 Webhook Check', 0x4aaac8),
    'KARMA_LOW':          ('📉 Karma Low', 0xd4b040),
    'KARMA_RESTORED':     ('📈 Karma Restored', 0x5cb84a),
    'KARMA_ADJUSTED':     ('⚖️ Karma Adjusted', 0xe8883a),
    'PROJECT_STATE':      ('📌 Project Update', 0x888880),
    'APPRECIATION':       ('❤️ Appreciation', 0xe06060),
    'FLAG_UP_RECEIVED':   ('🚩 Flag Received', 0xe06060),
    'FLAG_UP_SENT':       ('🚩 Flag Sent', 0x4aaac8),
    'NEW_USER':           ('🎉 New User', 0x7289da),
}


def _add_field(embed, name, value, inline=True):
    if value is not None and value != '':
        embed.add_field(name=name, value=value, inline=inline)


def _build_embed(event, payload):
    label, color = EVENT_META.get(event, (event, 0x888880))
    embed = discord.Embed(title=label, color=color)

    if event == 'KARMA_ADJUSTED':
        delta = payload.get('delta', 0)
        sign = '+' if delta >= 0 else ''
        _add_field(embed, 'Amount', f'`{sign}{delta}`')
        if payload.get('new_balance') is not None:
            _add_field(embed, 'New Balance', f'`{payload["new_balance"]}`')
        _add_field(embed, 'Reason', payload.get('reason'), inline=False)

    elif event == 'TASK_HEALTH_FAILED':
        _add_field(embed, 'Task', f'#{payload.get("task_id", "?")}')
        _add_field(embed, 'Reason', payload.get('health_last_failure_reason'), inline=False)

    elif event == 'WEBHOOK_CHECK':
        _add_field(embed, 'Task', f'#{payload.get("task_id", "?")}')
        _add_field(embed, 'Phase', payload.get('phase', '—'))
        _add_field(embed, 'Status', f'`{payload.get("status", "—")}`')
        _add_field(embed, 'Tester', payload.get('tester_username'))
        _add_field(embed, 'Detail', payload.get('detail'), inline=False)

    elif event in ('KARMA_LOW', 'KARMA_RESTORED'):
        _add_field(embed, 'Balance', f'`{payload.get("balance", "?")}`')
        _add_field(embed, 'Threshold', f'`{payload.get("threshold", "?")}`')

    elif event == 'NEW_USER':
        _add_field(embed, 'Username', payload.get('username', '—'))
        _add_field(embed, 'Total Users', f'`{payload.get("total_users", "?")}`')
        if payload.get('milestone'):
            _add_field(embed, '🏆 Milestone', f'**{payload["milestone"]} users!**', inline=False)

    else:
        if payload.get('task_id'):
            _add_field(embed, 'Task', f'#{payload["task_id"]}')
        if payload.get('balance') is not None:
            _add_field(embed, 'Balance', f'`{payload["balance"]}`')
        if payload.get('status'):
            _add_field(embed, 'Status', f'`{payload["status"]}`')

    embed.set_footer(text='KarmaRace')
    return embed.to_dict()


def _load_preference(preference_id, with_user=False):
    qs = NotificationPreference.objects
    if with_user:
        qs = qs.select_related('user')
    try:
        return qs.get(pk=preference_id)
    except NotificationPreference.DoesNotExist:
        logger.error('notification preference %s not found', preference_id)
        return None


def _record_delivery(pref, channel, payload, state, attempt):
    NotificationDelivery.objects.create(
        preference=pref, channel=channel,
        payload=payload, state=state, attempts=attempt,
    )


def _retry_or_log(task_fn, preference_id, payload, attempt, max_attempts):
    if attempt < max_attempts:
        try:
            task_fn.defer(preference_id=preference_id, payload=payload,
                          attempt=attempt + 1, max_attempts=max_attempts)
        except Exception as defer_exc:
            logger.error('retry enqueue failed for preference %s: %s', preference_id, defer_exc)


@app.task
def deliver_notification_webhook(preference_id: int, payload: dict, attempt: int = 1, max_attempts: int = 3):
    pref = _load_preference(preference_id)
    if not pref:
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

    _record_delivery(pref, NotificationDelivery.Channel.WEBHOOK, payload, state, attempt)


@app.task
def deliver_notification_discord(preference_id: int, payload: dict, attempt: int = 1, max_attempts: int = 3):
    pref = _load_preference(preference_id, with_user=True)
    if not pref:
        return

    from accounts.models import LinkedAccount
    from accounts import discord as discord_api

    discord_link = LinkedAccount.objects.filter(
        user=pref.user, platform=LinkedAccount.DISCORD,
    ).first()

    if not discord_link:
        logger.info('deliver_notification_discord: user %s has no linked Discord', pref.user_id)
        _record_delivery(pref, NotificationDelivery.Channel.DISCORD, payload,
                         NotificationDelivery.State.FAILED, attempt)
        return

    state = NotificationDelivery.State.FAILED
    try:
        embed = _build_embed(pref.event, payload)

        # Get or create the user's private notifs thread.
        thread_id = discord_link.discord_notifs_thread_id
        if not thread_id:
            thread_id = discord_api.create_notifs_thread(
                karmarace_username=pref.user.username,
                discord_user_id=discord_link.platform_id,
            )
            discord_link.discord_notifs_thread_id = thread_id
            discord_link.save(update_fields=['discord_notifs_thread_id'])

        discord_api.post_to_thread(thread_id, embed)
        state = NotificationDelivery.State.SUCCESS

    except Exception as exc:
        logger.error('deliver_notification_discord: attempt %s/%s failed for preference %s: %s',
                     attempt, max_attempts, preference_id, exc)
        _retry_or_log(deliver_notification_discord, preference_id, payload, attempt, max_attempts)

    _record_delivery(pref, NotificationDelivery.Channel.DISCORD, payload, state, attempt)