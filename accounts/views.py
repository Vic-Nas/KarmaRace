import secrets
from urllib.parse import urlencode

import requests
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts import discord as discord_api
from accounts.models import LinkedAccount, UserPreference
from notifications.models import Notification, NotificationPreference
from setup.platform_rules import KARMA_HIGH_THRESHOLD, KARMA_LOW_THRESHOLD


@login_required
def linked_accounts(request):
	github_social = SocialAccount.objects.filter(user=request.user, provider='github').first()
	if github_social:
		github_token = SocialToken.objects.filter(account=github_social).order_by('-pk').first()
		LinkedAccount.objects.update_or_create(
			user=request.user,
			platform=LinkedAccount.GITHUB,
			defaults={
				'platform_id': github_social.uid,
				'platform_username': (
					github_social.extra_data.get('login')
					or github_social.extra_data.get('username')
					or request.user.username
				),
				'access_token': github_token.token if github_token else '',
			},
		)

	github = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.GITHUB).first()
	discord = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.DISCORD).first()

	return render(request, 'accounts/linked_accounts.html', {
		'github': github,
		'discord': discord,
	})


@login_required
def connect_account(request, platform):
	if platform == LinkedAccount.GITHUB:
		return redirect('/accounts/github/login/?process=connect&next=/app/accounts/linked-accounts/')

	if platform == LinkedAccount.DISCORD:
		if not discord_api.is_configured():
			messages.error(request, 'Discord integration is not configured.')
			return redirect('linked_accounts')

		state = secrets.token_urlsafe(24)
		request.session['discord_oauth_state'] = state
		redirect_uri = request.build_absolute_uri('/app/accounts/discord/callback/')
		return redirect(discord_api.authorize_url(redirect_uri=redirect_uri, state=state))

	messages.error(request, 'Unknown platform.')
	return redirect('linked_accounts')


@login_required
def github_connect(request):
	return connect_account(request, LinkedAccount.GITHUB)


def _redirect_login_with_next(request):
	next_url = request.get_full_path()
	params = urlencode({'next': next_url})
	return redirect(f"/accounts/login/?{params}")


def _sync_discord_membership_for_link(request, linked: LinkedAccount):
	"""
	Returns True only when linked Discord account is still a guild member.
	Returns False when membership is missing (and stale mapping is deleted).
	Returns None when membership check fails due to API error.
	"""
	try:
		if discord_api.is_member(linked.platform_id):
			# Keep guild profile aligned with current app username.
			discord_api.sync_nickname(linked.platform_id, request.user.username)
			discord_api.ensure_role(linked.platform_id)
			return True
	except requests.RequestException:
		messages.warning(request, 'Could not verify Discord membership right now. Please try again.')
		return None

	linked.delete()
	messages.info(request, 'Discord link expired because account is no longer in the server. Please reconnect.')
	return False


def discord_entry(request):
	if not request.user.is_authenticated:
		return _redirect_login_with_next(request)

	if not discord_api.is_configured():
		messages.error(request, 'Discord integration is not configured.')
		return redirect('linked_accounts')

	linked = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.DISCORD).first()
	if linked:
		membership_state = _sync_discord_membership_for_link(request, linked)
		if membership_state is True:
			return redirect(discord_api.guild_jump_url())
		if membership_state is None:
			return redirect('linked_accounts')

	return connect_account(request, LinkedAccount.DISCORD)


@login_required
def discord_callback(request):
	expected_state = request.session.pop('discord_oauth_state', None)
	state = request.GET.get('state')
	code = request.GET.get('code')

	if not expected_state or state != expected_state:
		messages.error(request, 'Discord OAuth state mismatch.')
		return redirect('linked_accounts')

	if not code:
		messages.error(request, 'Discord OAuth did not return an authorization code.')
		return redirect('linked_accounts')

	redirect_uri = request.build_absolute_uri('/app/accounts/discord/callback/')
	try:
		access_token = discord_api.exchange_code_for_token(code=code, redirect_uri=redirect_uri)
		identity = discord_api.fetch_identity(access_token)

		discord_api.ensure_guild_membership(
			discord_user_id=identity.user_id,
			user_access_token=access_token,
			nickname=request.user.username,
		)
		discord_api.ensure_role(identity.user_id)
		discord_api.sync_nickname(identity.user_id, request.user.username)

		LinkedAccount.objects.update_or_create(
			user=request.user,
			platform=LinkedAccount.DISCORD,
			defaults={
				'platform_id': identity.user_id,
				'platform_username': identity.username,
				'access_token': access_token,
			},
		)
		messages.success(request, 'Discord account linked successfully.')
		return redirect(discord_api.guild_jump_url())
	except (requests.RequestException, ValueError) as exc:
		messages.error(request, f'Discord linking failed: {exc}')

	return redirect('linked_accounts')


@login_required
@require_POST
def unlink_account(request, platform):
	if platform not in {LinkedAccount.GITHUB, LinkedAccount.DISCORD}:
		messages.error(request, 'Unknown platform.')
		return redirect('linked_accounts')

	if platform == LinkedAccount.GITHUB:
		SocialAccount.objects.filter(user=request.user, provider='github').delete()

	LinkedAccount.objects.filter(user=request.user, platform=platform).delete()
	messages.success(request, f'{platform.title()} account disconnected.')
	return redirect('linked_accounts')


@login_required
def preferences(request):
	if request.method == 'POST':
		low_raw = (request.POST.get('karma_low_threshold') or '').strip()
		high_raw = (request.POST.get('karma_high_threshold') or '').strip()

		try:
			low_value = int(low_raw)
			high_value = int(high_raw)
			if low_value < 0 or high_value < 0:
				raise ValueError('Thresholds must be non-negative.')
			if high_value <= low_value:
				raise ValueError('High threshold must be greater than low threshold.')
		except ValueError as exc:
			messages.error(request, str(exc))
			return redirect('preferences')

		UserPreference.objects.update_or_create(
			user=request.user,
			key='karma_low_threshold',
			defaults={'value': str(low_value)},
		)
		UserPreference.objects.update_or_create(
			user=request.user,
			key='karma_high_threshold',
			defaults={'value': str(high_value)},
		)

		if request.user.is_pro:
			webhook_url = (request.POST.get('webhook_url') or '').strip()
			webhook_secret = (request.POST.get('webhook_secret') or '').strip()

			for event, _ in Notification.Event.choices:
				email_enabled = request.POST.get(f'email_{event}') == '1'
				webhook_enabled = request.POST.get(f'webhook_{event}') == '1'
				defaults = {
					'email_enabled': email_enabled,
					'webhook_url': webhook_url if webhook_enabled else '',
				}

				if hasattr(NotificationPreference, 'webhook_secret'):
					defaults['webhook_secret'] = webhook_secret if webhook_enabled else ''
				if hasattr(NotificationPreference, 'webhook_enabled'):
					defaults['webhook_enabled'] = webhook_enabled

				NotificationPreference.objects.update_or_create(
					user=request.user,
					event=event,
					defaults=defaults,
				)

		messages.success(request, 'Preferences saved.')
		return redirect('preferences')

	prefs = {}
	webhook_url = ''
	webhook_secret = ''
	if request.user.is_pro:
		for pref in NotificationPreference.objects.filter(user=request.user):
			prefs[pref.event] = pref
			if not webhook_url and pref.webhook_url:
				webhook_url = pref.webhook_url
			if not webhook_secret and getattr(pref, 'webhook_secret', ''):
				webhook_secret = pref.webhook_secret

	low_pref = UserPreference.objects.filter(user=request.user, key='karma_low_threshold').first()
	high_pref = UserPreference.objects.filter(user=request.user, key='karma_high_threshold').first()

	low_threshold = low_pref.value if low_pref else str(KARMA_LOW_THRESHOLD)
	high_threshold = high_pref.value if high_pref else str(KARMA_HIGH_THRESHOLD)

	return render(request, 'accounts/preferences.html', {
		'prefs': prefs,
		'webhook_url': webhook_url,
		'webhook_secret': webhook_secret,
		'all_events': Notification.Event.choices,
		'low_threshold': low_threshold,
		'high_threshold': high_threshold,
	})

