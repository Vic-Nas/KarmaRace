# accounts/discord.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests
from discord_oauth2 import DiscordAuth
from django.conf import settings

logger = logging.getLogger(__name__)

DISCORD_API_BASE = 'https://discord.com/api/v10'


@dataclass
class DiscordIdentity:
    user_id: str
    username: str


def is_configured() -> bool:
    return bool(
        settings.DISCORD_CLIENT_ID
        and settings.DISCORD_CLIENT_SECRET
        and settings.DISCORD_BOT_TOKEN
        and settings.DISCORD_GUILD_ID
        and settings.DISCORD_USER_ROLE_ID
        and settings.DISCORD_STAFF_ROLE_ID
        and settings.DISCORD_SUPERUSER_ROLE_ID
    )


def _oauth_client(redirect_uri: str | None = None) -> DiscordAuth:
    callback = redirect_uri or f"https://{settings.DOMAIN}/app/accounts/discord/callback/"
    return DiscordAuth(settings.DISCORD_CLIENT_ID, settings.DISCORD_CLIENT_SECRET, callback)


def authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        'client_id': settings.DISCORD_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'scope': 'identify guilds.join',
        'state': state,
        'prompt': 'consent',
    }
    return requests.Request('GET', 'https://discord.com/api/oauth2/authorize', params=params).prepare().url


def exchange_code_for_token(code: str, redirect_uri: str) -> str:
    token_data = _oauth_client(redirect_uri).get_tokens(code)
    access_token = token_data.get('access_token', '').strip()
    if not access_token:
        raise ValueError('Discord token response missing access_token.')
    return access_token


def fetch_identity(access_token: str) -> DiscordIdentity:
    data = _oauth_client().get_user_data_from_token(access_token) or {}
    user_id = str(data.get('id') or '').strip()
    username = (data.get('username') or '').strip()
    if not user_id:
        raise ValueError('Discord identity response missing id.')
    return DiscordIdentity(user_id=user_id, username=username)


def _bot_request(method: str, path: str, **kwargs):
    url = f"{DISCORD_API_BASE}{path}"
    headers = {
        'Authorization': f'Bot {settings.DISCORD_BOT_TOKEN}',
        'Content-Type': 'application/json',
    }
    return requests.request(method, url, headers=headers, timeout=15, **kwargs)


def _request_ok(method: str, path: str, ok_statuses: set, **kwargs):
    resp = _bot_request(method, path, **kwargs)
    if resp.status_code not in ok_statuses:
        resp.raise_for_status()
    return resp


def is_member(discord_user_id: str) -> bool:
    resp = _request_ok(
        'GET', f"/guilds/{settings.DISCORD_GUILD_ID}/members/{discord_user_id}",
        ok_statuses={200, 404},
    )
    return resp.status_code == 200


def ensure_guild_membership(discord_user_id: str, user_access_token: str, nickname: str) -> None:
    _request_ok(
        'PUT', f"/guilds/{settings.DISCORD_GUILD_ID}/members/{discord_user_id}",
        json={'access_token': user_access_token, 'nick': nickname},
        ok_statuses={201, 204},
    )


def _resolve_role_id(discord_user_id: str, local_user: Optional[object]) -> str:
    user = local_user
    if user is None:
        try:
            from accounts.models import LinkedAccount
            la = (
                LinkedAccount.objects.filter(platform=LinkedAccount.DISCORD, platform_id=discord_user_id)
                .select_related('user')
                .first()
            )
            user = la.user if la else None
        except Exception:
            user = None

    if user and getattr(user, 'is_superuser', False) and getattr(settings, 'DISCORD_SUPERUSER_ROLE_ID', ''):
        return settings.DISCORD_SUPERUSER_ROLE_ID
    if user and getattr(user, 'is_staff', False) and getattr(settings, 'DISCORD_STAFF_ROLE_ID', ''):
        return settings.DISCORD_STAFF_ROLE_ID
    if getattr(settings, 'DISCORD_USER_ROLE_ID', ''):
        return settings.DISCORD_USER_ROLE_ID
    return getattr(settings, 'DISCORD_ROLE_ID', '') or ''


def ensure_role(discord_user_id: str, local_user: Optional[object] = None) -> None:
    """Ensure the appropriate role is assigned to the guild member."""
    role_id = _resolve_role_id(discord_user_id, local_user)
    if not role_id:
        return
    _request_ok(
        'PUT', f"/guilds/{settings.DISCORD_GUILD_ID}/members/{discord_user_id}/roles/{role_id}",
        ok_statuses={204},
    )


def sync_nickname(discord_user_id: str, nickname: str) -> None:
    # Discord returns 204 (no content) on success, 403 if the target is the
    # server owner or has a higher role than the bot (un-patchable by design).
    _request_ok(
        'PATCH', f"/guilds/{settings.DISCORD_GUILD_ID}/members/{discord_user_id}",
        json={'nick': nickname},
        ok_statuses={200, 204},
    )


def guild_jump_url() -> str:
    return f'https://discord.com/channels/{settings.DISCORD_GUILD_ID}'


def kick_member(discord_user_id: str) -> None:
    """Remove a member from the guild (404 treated as success)."""
    _request_ok(
        'DELETE', f"/guilds/{settings.DISCORD_GUILD_ID}/members/{discord_user_id}",
        ok_statuses={204, 404},
    )


def _delete_stale_notifs_threads(channel_id: str, thread_name: str) -> None:
    """Delete private threads in the notifs channel with the given name."""
    for endpoint in ('threads/active', 'threads/private/archived'):
        try:
            resp = _bot_request('GET', f"/channels/{channel_id}/{endpoint}")
            if resp.status_code != 200:
                continue
            data = resp.json()
            threads = data if isinstance(data, list) else data.get('threads', [])
            for thread in threads:
                if thread.get('name') == thread_name:
                    _bot_request('DELETE', f"/channels/{thread['id']}")
        except Exception as exc:
            logger.warning('_delete_stale_notifs_threads: %s', exc)


def create_notifs_thread(karmarace_username: str, discord_user_id: str) -> str:
    """Create a private notifs thread, add the user, and return the thread ID."""
    channel_id = settings.DISCORD_NOTIFS_CHANNEL_ID
    thread_name = f'notifs-{karmarace_username}'

    # Clean up any stale threads with the same name (e.g. from lost thread IDs)
    _delete_stale_notifs_threads(channel_id, thread_name)

    # Type 12 = GUILD_PRIVATE_THREAD
    resp = _bot_request(
        'POST', f"/channels/{channel_id}/threads",
        json={'name': thread_name, 'type': 12, 'invitable': False},
    )
    resp.raise_for_status()
    thread_id = resp.json()['id']

    add_thread_member(thread_id, discord_user_id)

    return thread_id


def add_thread_member(thread_id: str, discord_user_id: str) -> None:
    """Add a Discord user to an existing thread."""
    _request_ok(
        'PUT', f"/channels/{thread_id}/thread-members/{discord_user_id}",
        ok_statuses={200, 201, 204},
    )


def remove_thread_member(thread_id: str, discord_user_id: str) -> None:
    """Remove a Discord user from a thread (404 treated as success)."""
    _request_ok(
        'DELETE', f"/channels/{thread_id}/thread-members/{discord_user_id}",
        ok_statuses={200, 204, 404},
    )


def post_to_thread(thread_id: str, embed: dict) -> None:
    """Post an embed message to a thread."""
    _request_ok(
        'POST', f"/channels/{thread_id}/messages",
        json={'embeds': [embed]},
        ok_statuses={200},
    )


def notify_superusers_new_user(new_username: str, total_users: int, milestone: int | None) -> None:
    """Post a NEW_USER notification to all superusers who have a linked Discord notifs thread."""
    from accounts.models import LinkedAccount, User
    from notifications.tasks import _build_embed

    superuser_ids = User.objects.filter(is_superuser=True).values_list('pk', flat=True)
    discord_links = (
        LinkedAccount.objects
        .filter(user_id__in=superuser_ids, platform=LinkedAccount.DISCORD)
        .select_related('user')
    )

    payload = {'username': new_username, 'total_users': total_users}
    if milestone:
        payload['milestone'] = milestone
    embed = _build_embed('NEW_USER', payload)

    for link in discord_links:
        try:
            thread_id = link.discord_notifs_thread_id
            if not thread_id:
                thread_id = create_notifs_thread(
                    karmarace_username=link.user.username,
                    discord_user_id=link.platform_id,
                )
                link.discord_notifs_thread_id = thread_id
                link.save(update_fields=['discord_notifs_thread_id'])
            post_to_thread(thread_id, embed)
        except Exception as exc:
            logger.warning('notify_superusers_new_user: failed for user %s: %s', link.user_id, exc)