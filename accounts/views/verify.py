"""Webhook endpoint for KarmaRace task verification."""
import hmac
import hashlib
import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth import get_user_model

from accounts.models import LinkedAccount, VerifiedEmail
from tasks.models import TaskCompletion

User = get_user_model()
logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(['POST'])
def verify_karmarace_hook(request):
    """
    Webhook endpoint to verify KarmaRace onboarding requirements:
    - User has signed up
    - User has linked Discord or GitHub
    - User has completed at least 1 task
    
    Expected JSON payload:
    {
        "user_id": <int>,  # or "username": <str>
        "secret": "<token>"  # optional for verification
    }
    
    Returns:
    {
        "verified": true/false,
        "reason": "error message if not verified"
    }
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'verified': False, 'reason': 'Invalid JSON'}, status=400)

    # Get user by ID, username, or verified google_email
    user_id      = payload.get('user_id')
    username     = payload.get('username')
    google_email = payload.get('google_email', '').strip()

    if not user_id and not username and not google_email:
        return JsonResponse({'verified': False, 'reason': 'user_id, username, or google_email required'}, status=400)

    try:
        if user_id:
            user = User.objects.get(pk=user_id)
        elif username:
            user = User.objects.get(username=username)
        else:
            user = VerifiedEmail.objects.select_related('user').get(email=google_email).user
    except (User.DoesNotExist, VerifiedEmail.DoesNotExist):
        return JsonResponse({'verified': False, 'reason': 'User not found'})

    # Optional: verify secret token
    secret = payload.get('secret', '')
    expected_secret = getattr(settings, 'KARMARACE_HOOK_SECRET', '')
    if expected_secret and secret != expected_secret:
        logger.warning('KarmaRace webhook: invalid secret for user %s', user.username)
        return JsonResponse({'verified': False, 'reason': 'Invalid secret'}, status=403)

    # Check conditions
    # 1. User exists (already verified above)
    # 2. User has linked Discord or GitHub
    has_linked_account = LinkedAccount.objects.filter(
        user=user,
        platform__in=[LinkedAccount.GITHUB, LinkedAccount.DISCORD]
    ).exists()

    if not has_linked_account:
        return JsonResponse({'verified': False, 'reason': 'No linked Discord/GitHub account'})

    # 3. User has completed at least 1 task
    has_completed_task = TaskCompletion.objects.filter(
        tester=user,
        state=TaskCompletion.State.CONFIRMED
    ).exists()

    if not has_completed_task:
        return JsonResponse({'verified': False, 'reason': 'No completed tasks'})

    logger.info('KarmaRace webhook: verified user %s', user.username)
    return JsonResponse({'verified': True})
