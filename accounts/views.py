import secrets
from urllib.parse import urlencode

import requests
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.models import LinkedAccount


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
		state = secrets.token_urlsafe(24)
		request.session['ph_oauth_state'] = state
		redirect_uri = request.build_absolute_uri('/app/accounts/producthunt/callback/')

		params = urlencode({
			'client_id': settings.PH_CLIENT_ID,
			'redirect_uri': redirect_uri,
			'response_type': 'code',
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

