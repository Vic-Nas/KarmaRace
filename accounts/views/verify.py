"""Webhook endpoint for KarmaRace task verification."""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from accounts.models import LinkedAccount, VerifiedEmail
from tasks.models import TaskCompletion

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(['POST'])
def verify_karmarace_hook(request):
    """
    Verify KarmaRace onboarding requirements for a webhook task check.

    Expected payload: {"google_email": "<str>", "task_slug": "<str>"}

    Returns: {"verified": true/false, "reason": "<str if false>"}

    Checks:
    - google_email resolves to a known VerifiedEmail
    - User has at least one linked Discord or GitHub account
    - User has at least one confirmed task completion
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'verified': False, 'reason': 'Invalid JSON'}, status=400)

    google_email = payload.get('google_email', '').strip()
    if not google_email:
        return JsonResponse({'verified': False, 'reason': 'google_email required'}, status=400)

    try:
        user = VerifiedEmail.objects.select_related('user').get(email=google_email).user
    except VerifiedEmail.DoesNotExist:
        return JsonResponse({'verified': False, 'reason': 'User not found'})

    if not LinkedAccount.objects.filter(
        user=user,
        platform__in=[LinkedAccount.GITHUB, LinkedAccount.DISCORD],
    ).exists():
        return JsonResponse({'verified': False, 'reason': 'No linked Discord/GitHub account'})

    if not TaskCompletion.objects.filter(
        tester=user,
        state=TaskCompletion.State.CONFIRMED,
    ).exists():
        return JsonResponse({'verified': False, 'reason': 'No completed tasks'})

    logger.info('verify_karmarace_hook: verified user %s', user.username)
    return JsonResponse({'verified': True})