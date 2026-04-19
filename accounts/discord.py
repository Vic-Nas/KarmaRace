from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings


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
        and settings.DISCORD_ROLE_ID
    )


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
    resp = requests.post(
        'https://discord.com/api/oauth2/token',
        data={
            'client_id': settings.DISCORD_CLIENT_ID,
            'client_secret': settings.DISCORD_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=15,
    )
    resp.raise_for_status()
    token_data = resp.json()
    access_token = token_data.get('access_token', '').strip()
    if not access_token:
        raise ValueError('Discord token response missing access_token.')
    return access_token


def fetch_identity(access_token: str) -> DiscordIdentity:
    resp = requests.get(
        f'{DISCORD_API_BASE}/users/@me',
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    user_id = str(data.get('id') or '').strip()
    username = (data.get('username') or '').strip()
    if not user_id:
        raise ValueError('Discord identity response missing id.')
    return DiscordIdentity(user_id=user_id, username=username)


def _bot_headers() -> dict:
    return {
        'Authorization': f'Bot {settings.DISCORD_BOT_TOKEN}',
        'Content-Type': 'application/json',
    }


def _member_url(discord_user_id: str) -> str:
    return f"{DISCORD_API_BASE}/guilds/{settings.DISCORD_GUILD_ID}/members/{discord_user_id}"


def is_member(discord_user_id: str) -> bool:
    resp = requests.get(_member_url(discord_user_id), headers=_bot_headers(), timeout=15)
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    return True


def ensure_guild_membership(discord_user_id: str, user_access_token: str, nickname: str) -> None:
    resp = requests.put(
        _member_url(discord_user_id),
        headers=_bot_headers(),
        json={
            'access_token': user_access_token,
            'nick': nickname,
        },
        timeout=15,
    )
    # Discord returns 201 (joined) or 204 (already in guild).
    if resp.status_code not in {201, 204}:
        resp.raise_for_status()


def ensure_role(discord_user_id: str) -> None:
    resp = requests.put(
        f"{_member_url(discord_user_id)}/roles/{settings.DISCORD_ROLE_ID}",
        headers=_bot_headers(),
        timeout=15,
    )
    if resp.status_code != 204:
        resp.raise_for_status()


def sync_nickname(discord_user_id: str, nickname: str) -> None:
    resp = requests.patch(
        _member_url(discord_user_id),
        headers=_bot_headers(),
        json={'nick': nickname},
        timeout=15,
    )
    if resp.status_code != 200:
        resp.raise_for_status()


def guild_jump_url() -> str:
    return f'https://discord.com/channels/{settings.DISCORD_GUILD_ID}'
