import secrets
from urllib.parse import urlencode

import requests
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

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
	producthunt = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.PRODUCTHUNT).first()

	return render(request, 'accounts/linked_accounts.html', {
		'github': github,
		'producthunt': producthunt,
	})


@login_required
def connect_account(request, platform):
	if platform == LinkedAccount.GITHUB:
		return redirect('/accounts/github/login/?process=connect&next=/app/accounts/linked-accounts/')

	if platform == LinkedAccount.PRODUCTHUNT:
		if not settings.PH_CLIENT_ID or not settings.PH_CLIENT_SECRET:
			messages.error(
				request,
				'Product Hunt OAuth is not configured. Set PH_CLIENT_ID/PH_CLIENT_SECRET '
				'or PH_API_KEY/PH_API_SECRET in .env.',
			)
			return redirect('linked_accounts')

		state = secrets.token_urlsafe(24)
		request.session['ph_oauth_state'] = state
		redirect_uri = request.build_absolute_uri('/app/accounts/producthunt/callback/')

		params = urlencode({
			'client_id': settings.PH_CLIENT_ID,
			'redirect_uri': redirect_uri,
			'response_type': 'code',
			'scope': 'public',
			'state': state,
		})
		return redirect(f'https://api.producthunt.com/v2/oauth/authorize?{params}')

	messages.error(request, 'Unknown platform.')
	return redirect('linked_accounts')


@login_required
def github_connect(request):
	return connect_account(request, LinkedAccount.GITHUB)


@login_required
def producthunt_connect(request):
	return connect_account(request, LinkedAccount.PRODUCTHUNT)


@login_required
def producthunt_callback(request):
	expected_state = request.session.pop('ph_oauth_state', None)
	state = request.GET.get('state')
	code = request.GET.get('code')

	if not expected_state or state != expected_state:
		messages.error(request, 'Product Hunt OAuth state mismatch.')
		return redirect('linked_accounts')

	if not code:
		messages.error(request, 'Product Hunt OAuth did not return an authorization code.')
		return redirect('linked_accounts')

	redirect_uri = request.build_absolute_uri('/app/accounts/producthunt/callback/')
	try:
		token_resp = requests.post(
			'https://api.producthunt.com/v2/oauth/token',
			data={
				'grant_type': 'authorization_code',
				'client_id': settings.PH_CLIENT_ID,
				'client_secret': settings.PH_CLIENT_SECRET,
				'redirect_uri': redirect_uri,
				'code': code,
			},
			timeout=15,
		)
		token_resp.raise_for_status()
		token_data = token_resp.json()
		access_token = token_data.get('access_token', '')
		if not access_token:
			messages.error(request, 'Product Hunt OAuth token response was missing access_token.')
			return redirect('linked_accounts')

		profile_resp = requests.post(
			'https://api.producthunt.com/v2/api/graphql',
			json={'query': 'query { viewer { id username } }'},
			headers={
				'Authorization': f'Bearer {access_token}',
				'Content-Type': 'application/json',
			},
			timeout=15,
		)
		profile_resp.raise_for_status()
		viewer = profile_resp.json().get('data', {}).get('viewer') or {}

		platform_id = str(viewer.get('id') or f'producthunt-{request.user.pk}')
		username = (viewer.get('username') or '').strip()

		LinkedAccount.objects.update_or_create(
			user=request.user,
			platform=LinkedAccount.PRODUCTHUNT,
			defaults={
				'platform_id': platform_id,
				'platform_username': username,
				'access_token': access_token,
			},
		)
		messages.success(request, 'Product Hunt account linked successfully.')
	except requests.RequestException as exc:
		messages.error(request, f'Product Hunt OAuth failed: {exc}')

	return redirect('linked_accounts')


@login_required
@require_POST
def unlink_account(request, platform):
	if platform not in {LinkedAccount.GITHUB, LinkedAccount.PRODUCTHUNT}:
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

