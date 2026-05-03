"""Email verification via Google OAuth."""
import logging
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import VerifiedEmail

logger = logging.getLogger(__name__)


def _google_client_id():
	"""Get Google OAuth client ID from settings."""
	from django.conf import settings
	return settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']


def _exchange_google_code_for_email(code, redirect_uri):
	"""Exchange Google OAuth code for user's email address."""
	from django.conf import settings
	google_cfg = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']
	token_resp = requests.post('https://oauth2.googleapis.com/token', data={
		'code': code,
		'client_id': google_cfg['client_id'],
		'client_secret': google_cfg['secret'],
		'redirect_uri': redirect_uri,
		'grant_type': 'authorization_code',
	}, timeout=10)
	token_resp.raise_for_status()
	access_token = token_resp.json().get('access_token', '')
	if not access_token:
		raise ValueError('No access token returned by Google.')
	info_resp = requests.get(
		'https://www.googleapis.com/oauth2/v3/userinfo',
		headers={'Authorization': f'Bearer {access_token}'},
		timeout=10,
	)
	info_resp.raise_for_status()
	return (info_resp.json().get('email') or '').strip().lower()


@login_required
def verify_email_start(request):
	"""Initiate Google email verification flow."""
	state = secrets.token_urlsafe(24)
	request.session['email_verify_state'] = state
	redirect_uri = request.build_absolute_uri(reverse('verify_email_callback'))
	params = urlencode({
		'client_id': _google_client_id(),
		'redirect_uri': redirect_uri,
		'response_type': 'code',
		'scope': 'email',
		'state': state,
		'access_type': 'online',
		'prompt': 'select_account',
	})
	return redirect(f'https://accounts.google.com/o/oauth2/v2/auth?{params}')


@login_required
def verify_email_callback(request):
	"""Handle Google email verification callback."""
	code  = request.GET.get('code', '').strip()
	state = request.GET.get('state', '').strip()
	if not code or state != request.session.pop('email_verify_state', ''):
		messages.error(request, 'Email verification failed: invalid state or missing code.')
		return redirect('linked_accounts')
	try:
		redirect_uri = request.build_absolute_uri(reverse('verify_email_callback'))
		email = _exchange_google_code_for_email(code, redirect_uri)
	except requests.RequestException:
		messages.error(request, 'Could not reach Google right now. Please try again.')
		return redirect('linked_accounts')
	except Exception as exc:
		logger.exception('verify_email_callback: unexpected error for user %s', request.user.pk)
		if settings.DEBUG:
			messages.error(request, f'Email verification failed: {exc}')
		else:
			messages.error(request, 'Something went wrong during email verification. Please try again.')
		return redirect('linked_accounts')
	if not email:
		messages.error(request, 'Could not retrieve email from Google.')
		return redirect('linked_accounts')
	existing = VerifiedEmail.objects.filter(email=email).exclude(user=request.user).first()
	if existing:
		messages.error(request, f'{email} is already linked to another account.')
		return redirect('linked_accounts')
	_, created = VerifiedEmail.objects.get_or_create(user=request.user, email=email)
	if created:
		messages.success(request, f'{email} verified and added.')
	else:
		messages.info(request, f'{email} is already on your account.')
	return redirect('linked_accounts')


@login_required
@require_POST
def remove_verified_email(request, email_id):
	"""Remove a verified email from the user's account."""
	from allauth.socialaccount.models import SocialAccount
	
	ve = get_object_or_404(VerifiedEmail, pk=email_id, user=request.user)
	google_social = SocialAccount.objects.filter(user=request.user, provider='google').first()
	primary_email = (google_social.extra_data.get('email') or '').strip().lower() if google_social else ''
	if ve.email.lower() == primary_email:
		messages.error(request, 'Cannot remove your primary Google login email.')
		return redirect('linked_accounts')
	ve.delete()
	messages.success(request, f'{ve.email} removed.')
	return redirect('linked_accounts')