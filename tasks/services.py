# tasks/services.py
import logging
import requests
from django.utils import timezone
from django.db import transaction

from django.conf import settings

from tasks.models import Task, TaskCompletion, ReciprocityObligation
from tasks.check_feedback import msg
from setup.platform_rules import WEBHOOK_OBLIGATIONS_ENABLED

logger = logging.getLogger(__name__)

HEALTH_HIDE_THRESHOLD = 2
HEALTH_CHECK_ATTEMPTS = 3  # retries within a single run before counting as failure


# ---------------------------------------------------------------------------
# Verification dispatcher
# ---------------------------------------------------------------------------

def verify_task(task, tester) -> bool:
    """Dispatch to the correct verifier based on task type."""
    ok, _ = verify_task_with_details(task, tester)
    return ok


def verify_task_with_details(task, tester):
    """Run health check on arrival, then dispatch to verifier."""
    run_health_check(task)
    task.refresh_from_db(fields=['hidden'])
    if task.hidden:
        return False, msg('TASK_TEMPORARILY_UNAVAILABLE')

    dispatch = {
        Task.Type.GITHUB_STAR: verify_github_with_details,
        Task.Type.GITHUB_FORK: verify_github_with_details,
        Task.Type.WEBHOOK:     verify_webhook_with_details,
    }
    verifier = dispatch.get(task.type)
    if verifier is None:
        logger.error('verify_task: unknown task type %s', task.type)
        return False, msg('UNKNOWN_TASK_TYPE')
    return verifier(task, tester)


# ---------------------------------------------------------------------------
# Platform verifiers
# ---------------------------------------------------------------------------

def verify_github_with_details(task, tester):
    """
    Check star or fork via GitHub API using server credentials.
    task.target_id must be the repo full name, e.g. "owner/repo".
    tester must have a linked GitHub account with platform_username set.
    """
    username, user_token = _get_github_identity(tester)
    if not username:
        logger.info('verify_github: tester %s has no linked GitHub account', tester.pk)
        return False, msg('GITHUB_LINK_REQUIRED')

    repo     = task.target_id

    if not _is_valid_github_repo_target(repo):
        return False, msg('TARGET_OWNER_REPO_REQUIRED')

    try:
        if task.type == Task.Type.GITHUB_STAR:
            if not user_token:
                return False, msg('GITHUB_TOKEN_RECONNECT')

            response = requests.get(
                f'https://api.github.com/user/starred/{repo}',
                headers=_github_headers(token_override=user_token),
                timeout=10,
            )
            if response.status_code == 204:
                return True, msg('GITHUB_STAR_VERIFIED')
            if response.status_code == 404:
                return False, msg('GITHUB_STAR_NOT_FOUND', username=username)
            if response.status_code in (401, 403):
                return False, msg('GITHUB_TOKEN_INVALID')
            return False, msg('GITHUB_STATUS_STAR', status=response.status_code)

        else:
            if not user_token:
                return False, msg('GITHUB_TOKEN_RECONNECT')

            # One-path check: ask the authenticated linked user for the specific repo.
            response = requests.get(
                f'https://api.github.com/repos/{username}/{repo.split("/", 1)[1]}',
                headers=_github_headers(token_override=user_token),
                timeout=10,
            )
            if response.status_code == 200 and response.json().get('fork') is True:
                return True, msg('GITHUB_FORK_VERIFIED')
            if response.status_code == 404:
                return False, msg('GITHUB_FORK_NOT_FOUND', username=username)
            if response.status_code in (401, 403):
                return False, msg('GITHUB_TOKEN_INVALID')
            return False, msg('GITHUB_STATUS_FORK', status=response.status_code)

    except requests.RequestException as exc:
        logger.error('verify_github: request failed for task %s: %s', task.pk, exc)
        return False, msg('GITHUB_REQUEST_FAILED', error=exc)


def verify_webhook_with_details(task, tester):
    """
    POST {"task_slug": ..., "platform_username": ...} to owner endpoint.
    Sends Authorization: Bearer <webhook_secret> header if set.
    Expects {"verified": true/false} in response.
    task.target_id is the webhook endpoint URL.
    """
    platform_username = (
        tester.linked_accounts
        .filter(platform='github')
        .values_list('platform_username', flat=True)
        .first()
    ) or ''

    headers = {}
    if task.webhook_secret:
        headers['Authorization'] = f'Bearer {task.webhook_secret}'

    task_slug = _task_slug(task)

    try:
        response = requests.post(
            task.target_id,
            json={'task_slug': task_slug, 'platform_username': platform_username},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
        verified = body.get('verified', False)
        if verified:
            return True, msg('WEBHOOK_VERIFIED')
        got_preview = str(body)
        if len(got_preview) > 300:
            got_preview = got_preview[:300] + '...'
        return False, msg(
            'WEBHOOK_NOT_VERIFIED',
            sent=f'{{"task_slug": "{task_slug}", "platform_username": "{platform_username}"}}',
            expected='{"verified": true}',
            got=got_preview,
        )
    except requests.RequestException as exc:
        logger.error('verify_webhook: request failed for task %s: %s', task.pk, exc)
        return False, msg(
            'WEBHOOK_REQUEST_FAILED',
            sent=f'{{"task_slug": "{task_slug}", "platform_username": "{platform_username}"}}',
            expected='{"verified": true}',
            error=exc,
        )
    except ValueError:
        return False, msg('WEBHOOK_BAD_JSON', expected='{"verified": true}')


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------

def soft_delete_task(task):
    """
    Soft-delete a task:
    - Sets is_deleted=True.
    - Auto-fails all PENDING completions for this task.
    """
    task.is_deleted = True
    task.save(update_fields=['is_deleted'])

    TaskCompletion.objects.filter(
        task=task,
        state=TaskCompletion.State.PENDING,
    ).update(
        state=TaskCompletion.State.FAILED,
        result_detail=msg('ARCHIVED_DURING_CHECK'),
    )


@transaction.atomic
def settle_or_create_obligation(actor, counterparty, task_type, completed_task):
    """Settle existing debt first; otherwise create reverse obligation."""
    if actor.pk == counterparty.pk:
        return None

    if task_type == Task.Type.WEBHOOK and not WEBHOOK_OBLIGATIONS_ENABLED:
        return 'ignored_webhook'

    debt = ReciprocityObligation.objects.select_for_update().filter(
        debtor=actor,
        creditor=counterparty,
        task_type=task_type,
        state=ReciprocityObligation.State.OPEN,
    ).order_by('created_at').first()

    if debt:
        debt.state = ReciprocityObligation.State.FULFILLED
        debt.fulfilled_by_task = completed_task
        debt.fulfilled_at = timezone.now()
        debt.save(update_fields=['state', 'fulfilled_by_task', 'fulfilled_at'])
        return 'settled'

    ReciprocityObligation.objects.create(
        debtor=counterparty,
        creditor=actor,
        task_type=task_type,
        state=ReciprocityObligation.State.OPEN,
        source_task=completed_task,
    )
    return 'created'


# ---------------------------------------------------------------------------
# Configuration check (runs at publish time)
# ---------------------------------------------------------------------------

def get_task_configuration_failure(task):
    """Return None when valid, otherwise a human-readable reason."""
    if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
        return _check_github_repo_public_detailed(task)
    elif task.type == Task.Type.WEBHOOK:
        pro_gate = _check_webhook_owner_plan_detailed(task)
        if pro_gate is not None:
            return pro_gate
        detail = _check_webhook_endpoint_contract_detailed(task)
        if detail is not None:
            logger.warning('get_task_configuration_failure: webhook check failed for task %s: %s', task.pk, detail)
            return _webhook_user_facing_reason(detail)
        return None

    logger.warning('get_task_configuration_failure: unknown task type %s', task.type)
    return 'Unknown task type.'


def _is_valid_github_repo_target(target):
    if not target or target.count('/') != 1:
        return False
    owner, repo = target.split('/')
    return bool(owner.strip()) and bool(repo.strip())


def _check_github_repo_public_detailed(task):
    if not _is_valid_github_repo_target(task.target_id):
        return 'GitHub target must be owner/repo format.'

    try:
        response = requests.get(
            f'https://api.github.com/repos/{task.target_id}',
            headers=_github_headers(),
            timeout=10,
        )
        if response.status_code == 200:
            if response.json().get('private', True):
                logger.warning(
                    'on_task_created: GitHub repo %s is private (task %s)',
                    task.target_id, task.pk,
                )
                return 'GitHub repo is private. Feed tasks require a public repo.'
            return None
        elif response.status_code == 404:
            return 'GitHub repo not found. Check owner/repo spelling.'
        else:
            logger.warning(
                'on_task_created: GitHub repo %s not found (task %s, status %s)',
                task.target_id, task.pk, response.status_code,
            )
            return f'GitHub API returned status {response.status_code} while checking repo.'
    except requests.RequestException as exc:
        logger.error('on_task_created: GitHub check failed for task %s: %s', task.pk, exc)
        return f'GitHub repo check failed: {exc}'


def _check_webhook_endpoint_contract_detailed(task):
    """POST probe payload and require JSON with boolean 'verified'."""
    from urllib.parse import urlparse
    parsed = urlparse(task.target_id)
    if not parsed.scheme or not parsed.netloc:
        return (
            'Webhook target is invalid. '
            f'Sent: {task.target_id}; '
            'Expected: full http/https URL; '
            'Got: missing scheme or host.'
        )
    probe_slug = _task_slug(task)
    expected = '{"verified": true|false}'
    payload = {
        'task_slug': probe_slug,
        'platform_username': 'probe-user',
    }
    headers = {'Content-Type': 'application/json'}
    if task.webhook_secret:
        headers['Authorization'] = f'Bearer {task.webhook_secret}'

    try:
        response = requests.post(
            task.target_id,
            json=payload,
            headers=headers,
            timeout=10,
        )
        body = response.text

        try:
            decoded = response.json()
        except ValueError:
            return (
                'Webhook endpoint contract check failed. '
                f'Sent: POST {task.target_id} body={payload}; '
                f'Expected: {expected}; '
                f'Got: status={response.status_code} non-JSON body={body[:300]}.'
            )

        verified = decoded.get('verified', None)
        if isinstance(verified, bool):
            return None

        return (
            'Webhook endpoint contract check failed. '
            f'Sent: POST {task.target_id} body={payload}; '
            f'Expected: {expected}; '
            f'Got: status={response.status_code} json={decoded}.'
        )
    except requests.RequestException as exc:
        return (
            'Webhook endpoint contract check failed. '
            f'Sent: POST {task.target_id} body={payload}; '
            f'Expected: {expected}; '
            f'Got: request error={exc}.'
        )


def _webhook_user_facing_reason(detail):
    if 'missing scheme or host' in detail:
        return 'Webhook URL is invalid. Use a full http/https URL.'
    if 'non-JSON body' in detail:
        return 'Webhook endpoint must return JSON with "verified": true or false.'
    if 'request error=' in detail:
        return 'Webhook endpoint is unreachable from the server.'
    return 'Webhook endpoint must return JSON with "verified": true or false.'


def _check_webhook_owner_plan_detailed(task):
    if not getattr(task.owner, 'is_pro', False):
        return 'Webhook tasks are Pro-only.'
    return None


# ---------------------------------------------------------------------------
# Unhide hook
# ---------------------------------------------------------------------------

def on_task_unhidden(task):
    """
    Called when a task's hidden flag is set back to False.
    Unarchives this task for users who have not already confirmed it.
    """
    completed_user_ids = TaskCompletion.objects.filter(
        task=task,
        state=TaskCompletion.State.CONFIRMED,
    ).values_list('tester_id', flat=True)

    users_to_unarchive = task.archived_by.exclude(id__in=completed_user_ids)
    if users_to_unarchive:
        task.archived_by.remove(*users_to_unarchive)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def run_health_check(task) -> bool:
    """
    Retries the health check up to HEALTH_CHECK_ATTEMPTS times before counting a failure.
    Two-strike policy on consecutive failed runs:
    - First run failure: marks suspect, does not hide.
    - Second run failure: hides task and notifies owner.
    - A healthy run resets streak and auto-unhides — unless owner manually unpublished.

    Returns True if healthy, False if failed.
    """
    healthy, reason = _check_task_health_with_retry(task)

    update_fields = ['health_last_checked_at']
    task.health_last_checked_at = timezone.now()

    if healthy:
        was_health_hidden = task.hidden and task.health_failure_streak >= HEALTH_HIDE_THRESHOLD
        if task.health_failure_streak != 0:
            task.health_failure_streak = 0
            update_fields.append('health_failure_streak')
        if task.health_last_failure_reason:
            task.health_last_failure_reason = ''
            update_fields.append('health_last_failure_reason')
        if was_health_hidden and not task.owner_unpublished:
            task.hidden = False
            update_fields.append('hidden')

        task.save(update_fields=update_fields)

        if was_health_hidden and not task.owner_unpublished:
            on_task_unhidden(task)

        return True

    task.health_failure_streak += 1
    task.health_last_failure_reason = reason or 'Health check failed.'
    update_fields.extend(['health_failure_streak', 'health_last_failure_reason'])

    should_hide = task.health_failure_streak >= HEALTH_HIDE_THRESHOLD
    transitioned_to_hidden = should_hide and not task.hidden
    if transitioned_to_hidden:
        task.hidden = True
        update_fields.append('hidden')

    task.save(update_fields=update_fields)

    if transitioned_to_hidden:
        _notify_health_failed(task)

    return False


def _check_task_health_with_retry(task):
    """
    Attempts the health check up to HEALTH_CHECK_ATTEMPTS times.
    Returns (True, '') on first success; (False, last_reason) if all attempts fail.
    Exponential backoff between attempts (1s, 2s, …).
    """
    import time
    reason = 'Health check failed.'
    for attempt in range(1, HEALTH_CHECK_ATTEMPTS + 1):
        healthy, reason = _check_task_health_with_reason(task)
        if healthy:
            return True, ''
        if attempt < HEALTH_CHECK_ATTEMPTS:
            time.sleep(2 ** (attempt - 1))
    return False, reason


def _notify_health_failed(task):
    """Notify the task owner directly when a task is hidden by health failure."""
    try:
        from notifications.models import Notification
        from notifications.services import notify
        notify(
            user=task.owner,
            event=Notification.Event.TASK_HEALTH_FAILED,
            payload={
                'task_id': task.pk,
                'task_type': task.type,
                'target_id': task.target_id,
                'owner_id': task.owner_id,
            },
        )
    except Exception as exc:
        logger.error('_notify_health_failed: failed for task %s: %s', task.pk, exc)


def _check_task_health_with_reason(task):
    """Returns True if the external resource is still reachable / valid."""
    try:
        if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
            response = requests.get(
                f'https://api.github.com/repos/{task.target_id}',
                headers=_github_headers(),
                timeout=10,
            )
            if response.status_code != 200:
                return False, f'GitHub health check returned status {response.status_code}.'
            if response.json().get('private', True):
                return False, 'GitHub repo is private.'
            return True, ''

        elif task.type == Task.Type.WEBHOOK:
            if _check_webhook_owner_plan_detailed(task) is not None:
                return False, 'Webhook tasks are Pro-only.'
            webhook_reason = _check_webhook_endpoint_contract_detailed(task)
            if webhook_reason is None:
                return True, ''
            return False, _webhook_user_facing_reason(webhook_reason)

    except requests.RequestException as exc:
        logger.error('run_health_check: request failed for task %s: %s', task.pk, exc)
        return False, f'External request failed: {exc}'

    return False, 'Unknown task type for health check.'



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_github_identity(tester):
    """Return (username, access_token) from LinkedAccount and allauth fallback."""
    username = ''
    access_token = ''

    linked = tester.linked_accounts.filter(platform='github').first()
    if linked:
        username = (linked.platform_username or '').strip()
        access_token = (linked.access_token or '').strip()

    # Fallback to allauth social identity if LinkedAccount fields are stale/missing.
    try:
        from allauth.socialaccount.models import SocialAccount, SocialToken

        social = SocialAccount.objects.filter(user=tester, provider='github').first()
        if social:
            if not username:
                username = (
                    social.extra_data.get('login')
                    or social.extra_data.get('username')
                    or ''
                ).strip()
            if not access_token:
                token = SocialToken.objects.filter(account=social).order_by('-pk').first()
                access_token = (token.token if token else '') or ''
    except Exception as exc:
        logger.warning('verify_github: allauth fallback lookup failed for tester %s: %s', tester.pk, exc)

    return username, access_token


def _task_slug(task):
    """Deterministic slug for webhook verification payloads."""
    platform_map = {
        Task.Type.GITHUB_STAR: 'github-star',
        Task.Type.GITHUB_FORK: 'github-fork',
        Task.Type.WEBHOOK: 'webhook',
    }
    platform = platform_map.get(task.type, 'task')
    target_component = _slug_component(task.target_id)
    owner_component = _slug_component(getattr(task.owner, 'username', '') or 'owner')
    return f'{platform}-{owner_component}-{target_component}'


def _slug_component(raw):
    value = (raw or '').strip().lower()
    if not value:
        return 'target'

    import re
    value = re.sub(r'[^a-z0-9]+', '-', value)
    value = value.strip('-')
    return value or 'target'


def _github_headers(token_override=None) -> dict:
    token = token_override or getattr(settings, 'GITHUB_TOKEN', None)
    headers = {'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers