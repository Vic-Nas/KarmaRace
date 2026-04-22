import secrets
from urllib.parse import urlencode

import requests
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts import discord as discord_api
from accounts.models import LinkedAccount, UserPreference, UserProfile
from notifications.models import Notification, NotificationPreference
from setup.platform_rules import KARMA_HIGH_THRESHOLD, KARMA_LOW_THRESHOLD


# ---------------------------------------------------------------------------
# Linked accounts
# ---------------------------------------------------------------------------

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
	params = urlencode({'process': 'login', 'next': next_url})
	return redirect(f"{reverse('google_login')}?{params}")


def _sync_discord_membership_for_link(request, linked: LinkedAccount):
	try:
		if discord_api.is_member(linked.platform_id):
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

	linked = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.DISCORD).first()
	if linked:
		result = _sync_discord_membership_for_link(request, linked)
		if result is True:
			return redirect(discord_api.guild_jump_url())
		elif result is False:
			return connect_account(request, LinkedAccount.DISCORD)
		return redirect('linked_accounts')

	return connect_account(request, LinkedAccount.DISCORD)


def discord_callback(request):
	if not request.user.is_authenticated:
		return _redirect_login_with_next(request)

	code = request.GET.get('code', '').strip()
	state = request.GET.get('state', '').strip()
	expected_state = request.session.pop('discord_oauth_state', '')

	if not code or state != expected_state:
		messages.error(request, 'Discord OAuth failed: invalid state or missing code.')
		return redirect('linked_accounts')

	try:
		redirect_uri = request.build_absolute_uri('/app/accounts/discord/callback/')
		access_token = discord_api.exchange_code_for_token(code, redirect_uri)
		identity = discord_api.fetch_identity(access_token)

		discord_api.ensure_guild_membership(identity.user_id, access_token, request.user.username)
		discord_api.ensure_role(identity.user_id)

		LinkedAccount.objects.update_or_create(
			user=request.user,
			platform=LinkedAccount.DISCORD,
			defaults={
				'platform_id': identity.user_id,
				'platform_username': identity.username,
			},
		)
		messages.success(request, 'Discord account linked.')
	except Exception as exc:
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


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

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
			user=request.user, key='karma_low_threshold', defaults={'value': str(low_value)},
		)
		UserPreference.objects.update_or_create(
			user=request.user, key='karma_high_threshold', defaults={'value': str(high_value)},
		)

		if request.user.is_pro:
			webhook_url = (request.POST.get('webhook_url') or '').strip()
			webhook_secret = (request.POST.get('webhook_secret') or '').strip()

			for event, _ in Notification.Event.choices:
				email_enabled = request.POST.get(f'email_{event}') == '1'
				webhook_enabled = request.POST.get(f'webhook_{event}') == '1'
				discord_enabled = request.POST.get(f'discord_{event}') == '1'

				defaults = {
					'email_enabled': email_enabled,
					'webhook_url': webhook_url if webhook_enabled else '',
					'discord_enabled': discord_enabled,
				}
				if hasattr(NotificationPreference, 'webhook_secret'):
					defaults['webhook_secret'] = webhook_secret if webhook_enabled else ''

				NotificationPreference.objects.update_or_create(
					user=request.user, event=event, defaults=defaults,
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

	has_discord = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.DISCORD).exists()

	return render(request, 'accounts/preferences.html', {
		'prefs': prefs,
		'webhook_url': webhook_url,
		'webhook_secret': webhook_secret,
		'all_events': Notification.Event.choices,
		'low_threshold': low_pref.value if low_pref else str(KARMA_LOW_THRESHOLD),
		'high_threshold': high_pref.value if high_pref else str(KARMA_HIGH_THRESHOLD),
		'has_discord': has_discord,
	})


# ---------------------------------------------------------------------------
# Public profile
# ---------------------------------------------------------------------------

def public_profile(request, username):
	from django.contrib.auth import get_user_model
	from karma.services import get_balance
	from tasks.models import Task, TaskCompletion

	User = get_user_model()
	profile_user = get_object_or_404(User, username=username)

	try:
		profile = profile_user.profile
	except UserProfile.DoesNotExist:
		profile = UserProfile(user=profile_user)

	karma = get_balance(profile_user)
	task_count = Task.objects.filter(owner=profile_user, is_deleted=False).count()
	completed_count = TaskCompletion.objects.filter(
		tester=profile_user, state=TaskCompletion.State.CONFIRMED,
	).count()

	github = None
	if profile.show_github:
		github = LinkedAccount.objects.filter(
			user=profile_user, platform=LinkedAccount.GITHUB,
		).first()

	is_own = request.user.is_authenticated and request.user == profile_user

	return render(request, 'accounts/profile.html', {
		'profile_user': profile_user,
		'profile': profile,
		'karma': karma if profile.show_karma else None,
		'task_count': task_count,
		'completed_count': completed_count,
		'github': github,
		'is_own': is_own,
	})


# ---------------------------------------------------------------------------
# Edit own profile
# ---------------------------------------------------------------------------

@login_required
def edit_profile(request):
	profile, _ = UserProfile.objects.get_or_create(user=request.user)

	if request.method == 'POST':
		profile.first_name    = (request.POST.get('first_name') or '').strip()[:100]
		profile.last_name     = (request.POST.get('last_name') or '').strip()[:100]
		profile.contact_email = (request.POST.get('contact_email') or '').strip()[:254]

		profile.show_first_name    = request.POST.get('show_first_name') == '1'
		profile.show_last_name     = request.POST.get('show_last_name') == '1'
		profile.show_contact_email = request.POST.get('show_contact_email') == '1'
		profile.show_github        = request.POST.get('show_github') == '1'
		profile.show_karma         = request.POST.get('show_karma') == '1'
		profile.show_joined        = request.POST.get('show_joined') == '1'
		profile.save()

		messages.success(request, 'Profile saved.')
		return redirect('public_profile', username=request.user.username)

	visibility_fields = [
		('show_first_name',    'First name',    profile.show_first_name),
		('show_last_name',     'Last name',     profile.show_last_name),
		('show_contact_email', 'Contact email', profile.show_contact_email),
		('show_github',        'GitHub link',   profile.show_github),
		('show_karma',         'Karma balance', profile.show_karma),
		('show_joined',        'Member since',  profile.show_joined),
	]
	return render(request, 'accounts/edit_profile.html', {
		'profile': profile,
		'visibility_fields': visibility_fields,
	})
