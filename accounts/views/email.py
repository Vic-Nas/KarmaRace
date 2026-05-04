# accounts/views/email.py
"""Email verification via Google OAuth."""
import logging
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow

from accounts.models import VerifiedEmail

logger = logging.getLogger(__name__)


def _google_client_id():
	"""Get Google OAuth client ID from settings."""
	return settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']


def _google_client_config():
	google_cfg = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']
	return {
		'web': {
			'client_id': google_cfg['client_id'],
			'client_secret': google_cfg['secret'],
			'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
			'token_uri': 'https://oauth2.googleapis.com/token',
		},
	}


def _build_flow(redirect_uri: str) -> Flow:
	flow = Flow.from_client_config(
		_google_client_config(),
		scopes=['openid', 'email'],
	)
	flow.redirect_uri = redirect_uri
	return flow


def _exchange_google_code_for_email(code, redirect_uri):
	"""Exchange Google OAuth code for user's email address."""
	flow = _build_flow(redirect_uri)
	flow.fetch_token(code=code)

	token_value = getattr(flow.credentials, 'id_token', None)
	if not token_value:
		raise ValueError('No ID token returned by Google.')

	info = id_token.verify_oauth2_token(
		token_value,
		google_requests.Request(),
		_google_client_id(),
	)
	return (info.get('email') or '').strip().lower()


@login_required
def verify_email_start(request):
	"""Initiate Google email verification flow."""
	state = secrets.token_urlsafe(24)
	request.session['email_verify_state'] = state
	redirect_uri = request.build_absolute_uri(reverse('verify_email_callback'))
	flow = _build_flow(redirect_uri)
	auth_url, _ = flow.authorization_url(
		access_type='online',
		prompt='select_account',
		state=state,
	)
	return redirect(auth_url)


@login_required
def verify_email_callback(request):
	"""Handle Google email verification callback."""
	code  = request.GET.get('code', '').strip()
	state = request.GET.get('state', '').strip()
	if not code or state != request.session.pop('email_verify_state', ''):
		messages.error(request, 'Email verification failed: invalid state or missing code.')
		return redirect('linked_accounts')
	email = _try_exchange_email(request, code)
	if email is None:
		return redirect('linked_accounts')
	if not email:
		messages.error(request, 'Could not retrieve email from Google.')
		return redirect('linked_accounts')
	existing = VerifiedEmail.objects.filter(email=email).exclude(user=request.user).first()
	if existing:
		messages.error(request, f'{email} is already linked to another account.')
		return redirect('linked_accounts')


	def _try_exchange_email(request, code):
		try:
			redirect_uri = request.build_absolute_uri(reverse('verify_email_callback'))
			return _exchange_google_code_for_email(code, redirect_uri)
		except (GoogleAuthError, ValueError):
			messages.error(request, 'Could not reach Google right now. Please try again.')
			return None
		except Exception as exc:
			logger.exception('verify_email_callback: unexpected error for user %s', request.user.pk)
			if settings.DEBUG:
				messages.error(request, f'Email verification failed: {exc}')
			else:
				messages.error(request, 'Something went wrong during email verification. Please try again.')
			return None
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