# accounts/views/linked.py
"""Linked account management and Discord OAuth."""
import logging
import secrets

import requests
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts import discord as discord_api
from accounts.models import LinkedAccount

logger = logging.getLogger(__name__)


@login_required
def linked_accounts(request):
    """Show linked accounts (GitHub, Discord) and verified emails."""
    _sync_github_link(request.user)
    github  = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.GITHUB).first()
    discord = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.DISCORD).first()
    google_social = SocialAccount.objects.filter(user=request.user, provider='google').first()
    primary_email = (google_social.extra_data.get('email') or '').strip().lower() if google_social else ''
    verified_emails = list(request.user.verified_emails.order_by('verified_at'))
    return render(request, 'accounts/linked_accounts.html', {
        'github': github,
        'discord': discord,
        'verified_emails': verified_emails,
        'primary_email': primary_email,
    })


@login_required
def connect_account(request, platform):
    """Initiate OAuth flow for a platform."""
    if platform == LinkedAccount.GITHUB:
        return redirect('/accounts/github/login/?process=connect&next=/app/accounts/linked-accounts/')
    if platform == LinkedAccount.DISCORD:
        if not discord_api.is_configured():
            messages.error(request, 'Discord integration is not configured.')
            return redirect('linked_accounts')
        return redirect(_discord_auth_url(request))
    messages.error(request, 'Unknown platform.')
    return redirect('linked_accounts')


def _sync_discord_membership(request, linked):
    """Verify Discord membership and sync role. Delete if membership expired."""
    try:
        if discord_api.is_member(linked.platform_id):
            discord_api.sync_nickname(linked.platform_id, request.user.username)
            discord_api.ensure_role(linked.platform_id)
            return True
    except requests.RequestException as exc:
        logger.error('_sync_discord_membership: failed for user %s: %s',
                     request.user.pk, exc, exc_info=True)
        messages.warning(request, 'Could not verify Discord membership right now. Please try again.')
        return None
    # User left the guild on their own — drop the DB record, no server kick.
    linked.delete()
    messages.info(request, 'Discord link expired. Please reconnect.')
    return False


def _sync_github_link(user):
    github_social = SocialAccount.objects.filter(user=user, provider='github').first()
    if not github_social:
        return
    github_token = SocialToken.objects.filter(account=github_social).order_by('-pk').first()
    LinkedAccount.objects.update_or_create(
        user=user,
        platform=LinkedAccount.GITHUB,
        defaults={
            'platform_id': github_social.uid,
            'platform_username': (
                github_social.extra_data.get('login')
                or github_social.extra_data.get('username')
                or user.username
            ),
            'access_token': github_token.token if github_token else '',
        },
    )


def _discord_auth_url(request):
    state = secrets.token_urlsafe(24)
    request.session['discord_oauth_state'] = state
    redirect_uri = request.build_absolute_uri('/app/accounts/discord/callback/')
    return discord_api.authorize_url(redirect_uri=redirect_uri, state=state)


@login_required
def discord_entry(request):
    """Entry point to Discord integration (check membership or initiate connect)."""
    linked = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.DISCORD).first()
    if linked:
        result = _sync_discord_membership(request, linked)
        if result is True:
            return redirect(discord_api.guild_jump_url())
        if result is False:
            return connect_account(request, LinkedAccount.DISCORD)
        return redirect('linked_accounts')
    return connect_account(request, LinkedAccount.DISCORD)


@login_required
def discord_callback(request):
    """Handle Discord OAuth callback."""
    code  = request.GET.get('code', '').strip()
    state = request.GET.get('state', '').strip()
    if not code or state != request.session.pop('discord_oauth_state', ''):
        messages.error(request, 'Discord OAuth failed: invalid state or missing code.')
        return redirect('linked_accounts')
    try:
        redirect_uri = request.build_absolute_uri('/app/accounts/discord/callback/')
        access_token = discord_api.exchange_code_for_token(code, redirect_uri)
        identity     = discord_api.fetch_identity(access_token)

        existing = LinkedAccount.objects.filter(
            user=request.user, platform=LinkedAccount.DISCORD,
        ).first()
        old_discord_id = existing.platform_id if existing else None
        inherited_thread = (existing.discord_notifs_thread_id if existing else None) or ''

        # Add new account to guild first (must happen before thread membership swap).
        discord_api.ensure_guild_membership(identity.user_id, access_token, request.user.username)
        discord_api.ensure_role(identity.user_id, request.user)

        # If replacing an old account: swap thread membership then kick old account.
        if old_discord_id and old_discord_id != identity.user_id:
            _swap_thread_member(inherited_thread, identity.user_id, old_discord_id)

        LinkedAccount.objects.update_or_create(
            user=request.user, platform=LinkedAccount.DISCORD,
            defaults={
                'platform_id':               identity.user_id,
                'platform_username':         identity.username,
                'discord_notifs_thread_id':  inherited_thread,
            },
        )
        messages.success(request, 'Discord account linked.')
    except IntegrityError:
        messages.error(request, 'This Discord account is already linked to another account.')
    except requests.RequestException:
        messages.error(request, 'Could not reach Discord right now. Please try again.')
    except Exception as exc:
        logger.exception('discord_callback: unexpected error for user %s', request.user.pk)
        if settings.DEBUG:
            messages.error(request, f'Discord linking failed: {exc}')
        else:
            messages.error(request, 'Something went wrong linking your Discord account. Please try again.')
    return redirect('linked_accounts')


def _swap_thread_member(thread_id, new_id, old_id):
    if thread_id:
        try:
            discord_api.add_thread_member(thread_id, new_id)
            discord_api.remove_thread_member(thread_id, old_id)
        except requests.RequestException as exc:
            logger.error('_swap_thread_member: failed for thread %s old=%s new=%s: %s',
                         thread_id, old_id, new_id, exc, exc_info=True)
    try:
        discord_api.kick_member(old_id)
    except requests.RequestException as exc:
        logger.error('_swap_thread_member: kick failed for old_id=%s: %s', old_id, exc, exc_info=True)


@login_required
@require_POST
def unlink_account(request, platform):
    """
    Unlink an account from the platform.
    Discord unlink: drops the DB record only. No guild kick, thread untouched.
    If the user re-links later with the same account the thread is reused;
    if they link a different account the callback handles the swap.
    """
    if platform not in {LinkedAccount.GITHUB, LinkedAccount.DISCORD}:
        messages.error(request, 'Unknown platform.')
        return redirect('linked_accounts')
    if platform == LinkedAccount.GITHUB:
        SocialAccount.objects.filter(user=request.user, provider='github').delete()
    LinkedAccount.objects.filter(user=request.user, platform=platform).delete()
    messages.success(request, f'{platform.title()} account disconnected.')
    return redirect('linked_accounts')