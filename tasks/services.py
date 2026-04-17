# tasks/services.py
import logging
import requests
from django.db import transaction

from django.conf import settings

from tasks.models import Task, TaskCompletion, ReciprocityObligation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Verification dispatcher
# ---------------------------------------------------------------------------

def verify_task(task, tester) -> bool:
    """Dispatch to the correct verifier based on task type."""
    ok, _ = verify_task_with_details(task, tester)
    return ok


def verify_task_with_details(task, tester):
    """Dispatch to verifier and return (ok, detail_message)."""
    dispatch = {
        Task.Type.GITHUB_STAR: verify_github_with_details,
        Task.Type.GITHUB_FORK: verify_github_with_details,
        Task.Type.PH_COMMENT:  verify_ph_with_details,
        Task.Type.WEBHOOK:     verify_webhook_with_details,
    }
    verifier = dispatch.get(task.type)
    if verifier is None:
        logger.error('verify_task: unknown task type %s', task.type)
        return False, 'Unknown task type.'
    return verifier(task, tester)


# ---------------------------------------------------------------------------
# Platform verifiers
# ---------------------------------------------------------------------------

def verify_github(task, tester) -> bool:
    ok, _ = verify_github_with_details(task, tester)
    return ok


def verify_github_with_details(task, tester):
    """
    Check star or fork via GitHub API using server credentials.
    task.target_id must be the repo full name, e.g. "owner/repo".
    tester must have a linked GitHub account with platform_username set.
    """
    username, user_token = _get_github_identity(tester)
    if not username:
        logger.info('verify_github: tester %s has no linked GitHub account', tester.pk)
        return False, 'Your GitHub account is not linked. Connect GitHub in Linked Accounts and try again.'

    repo     = task.target_id

    if not _is_valid_github_repo_target(repo):
        return False, 'Target must be in owner/repo format.'

    try:
        if task.type == Task.Type.GITHUB_STAR:
            if not user_token:
                return False, 'Linked GitHub token is missing. Reconnect your GitHub account and try again.'

            response = requests.get(
                f'https://api.github.com/user/starred/{repo}',
                headers=_github_headers(token_override=user_token),
                timeout=10,
            )
            if response.status_code == 204:
                return True, 'Verified GitHub star.'
            if response.status_code == 404:
                return False, (
                    f"We couldn't verify the star for @{username} yet. "
                    'Please star the public repo with your linked GitHub account, wait a minute, then press Check again.'
                )
            if response.status_code in (401, 403):
                return False, 'GitHub token is invalid or missing scope. Reconnect your GitHub account and try again.'
            return False, f'GitHub returned status {response.status_code} while checking star.'

        else:
            if not user_token:
                return False, 'Linked GitHub token is missing. Reconnect your GitHub account and try again.'

            # One-path check: ask the authenticated linked user for the specific repo.
            response = requests.get(
                f'https://api.github.com/repos/{username}/{repo.split("/", 1)[1]}',
                headers=_github_headers(token_override=user_token),
                timeout=10,
            )
            if response.status_code == 200 and response.json().get('fork') is True:
                return True, 'Verified GitHub fork.'
            if response.status_code == 404:
                return False, (
                    f"We couldn't verify a fork for @{username} yet. "
                    'Please fork the repo with your linked GitHub account, wait a minute, then press Check again.'
                )
            if response.status_code in (401, 403):
                return False, 'GitHub token is invalid or missing scope. Reconnect your GitHub account and try again.'
            return False, f'GitHub returned status {response.status_code} while checking fork.'

    except requests.RequestException as exc:
        logger.error('verify_github: request failed for task %s: %s', task.pk, exc)
        return False, f'GitHub verification request failed: {exc}'


def verify_ph(task, tester) -> bool:
    ok, _ = verify_ph_with_details(task, tester)
    return ok


def verify_ph_with_details(task, tester):
    """
    Check Product Hunt upvote or comment presence via PH GraphQL API.
    Uses tester's stored access_token for user-scoped queries.
    task.target_id must be a PH post slug.

    Either an upvote (isVoted) or a comment by the tester passes.
    Paginates through all comments using GraphQL cursor-based pagination.
    """
    try:
        linked = tester.linked_accounts.get(platform='producthunt')
    except tester.linked_accounts.model.DoesNotExist:
        logger.info('verify_ph: tester %s has no linked Product Hunt account', tester.pk)
        return False, 'Your Product Hunt account is not linked.'

    access_token = linked.access_token
    ph_user_id = (linked.platform_id or '').strip()
    ph_username = (linked.platform_username or '').strip().lower()

    ok, post_vars, id_mode_reason = _resolve_ph_post_query_vars(task.target_id)
    if not ok:
        return False, id_mode_reason

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type':  'application/json',
    }

    # First check isVoted — single cheap query, no pagination needed.
    voted_query = (
        'query(' + _ph_query_signature(post_vars) + ') '
        '{ post(' + _ph_query_arg(post_vars) + ') { isVoted } }'
    )
    try:
        response = requests.post(
            'https://api.producthunt.com/v2/api/graphql',
            json={'query': voted_query, 'variables': post_vars},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        post = data.get('data', {}).get('post')
        if not post:
            logger.warning('verify_ph: post target %s not found', task.target_id)
            return False, 'Product Hunt post not found. Use post slug.'
        if post.get('isVoted'):
            return True, 'Verified Product Hunt upvote.'
    except requests.RequestException as exc:
        logger.error('verify_ph: vote check failed for task %s: %s', task.pk, exc)
        return False, f'Product Hunt vote check failed: {exc}'

    # isVoted is False — check comments with cursor-based pagination.
    comments_query = (
        'query(' + _ph_query_signature(post_vars, include_cursor=True) + ') '
        '{ post(' + _ph_query_arg(post_vars) + ') '
        '{ comments(first: 100, after: $cursor) '
        '{ edges { node { user { id username } } } pageInfo { hasNextPage endCursor } } } }'
    )
    cursor = None
    try:
        while True:
            response = requests.post(
                'https://api.producthunt.com/v2/api/graphql',
                json={
                    'query': comments_query,
                    'variables': {**post_vars, 'cursor': cursor},
                },
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            data     = response.json()
            comments = data.get('data', {}).get('post', {}).get('comments', {})
            edges    = comments.get('edges', [])

            if any(_matches_ph_user(edge, ph_user_id, ph_username) for edge in edges):
                return True, 'Verified Product Hunt comment.'

            page_info = comments.get('pageInfo', {})
            if not page_info.get('hasNextPage'):
                return False, 'No upvote/comment detected for your Product Hunt account.'
            cursor = page_info.get('endCursor')

    except requests.RequestException as exc:
        logger.error('verify_ph: comment check failed for task %s: %s', task.pk, exc)
        return False, f'Product Hunt comment check failed: {exc}'


def verify_webhook(task, tester) -> bool:
    ok, _ = verify_webhook_with_details(task, tester)
    return ok


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
            return True, 'Webhook verified successfully.'
        return False, (
            'Webhook responded but did not verify. '
            f'Sent: {{"task_slug": "{task_slug}", "platform_username": "{platform_username}"}}; '
            f'Expected: {{"verified": true}}; Got: {body}'
        )
    except requests.RequestException as exc:
        logger.error('verify_webhook: request failed for task %s: %s', task.pk, exc)
        return False, (
            'Webhook request failed. '
            f'Sent: {{"task_slug": "{task_slug}", "platform_username": "{platform_username}"}}; '
            f'Expected: {{"verified": true}}; Error: {exc}'
        )
    except ValueError:
        return False, 'Webhook response is not valid JSON. Expected {"verified": true}.'


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
    ).update(state=TaskCompletion.State.FAILED)


@transaction.atomic
def settle_or_create_obligation(actor, counterparty, task_type, completed_task):
    """Settle existing debt first; otherwise create reverse obligation."""
    if actor.pk == counterparty.pk:
        return None

    debt = ReciprocityObligation.objects.select_for_update().filter(
        debtor=actor,
        creditor=counterparty,
        task_type=task_type,
        state=ReciprocityObligation.State.OPEN,
    ).order_by('created_at').first()

    if debt:
        debt.delete()
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
# Creation hook
# ---------------------------------------------------------------------------

def on_task_created(task):
    """
    Called after a new task is saved.
    - Runs upfront validity checks appropriate to the task type.
    """
    # Upfront validity checks: invalid tasks are auto-hidden.
    if not is_task_configuration_valid(task):
        task.hidden = True
        task.save(update_fields=['hidden'])


def is_task_configuration_valid(task) -> bool:
    """
    Returns True when a task appears externally valid/reachable.
    Used to gate activation and to auto-hide invalid tasks on creation/edit.
    """
    return get_task_configuration_failure(task) is None


def get_task_configuration_failure(task):
    """Return None when valid, otherwise a human-readable reason."""
    if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
        return _check_github_repo_public_detailed(task)
    elif task.type == Task.Type.PH_COMMENT:
        return _check_ph_post_exists_detailed(task)
    elif task.type == Task.Type.WEBHOOK:
        pro_gate = _check_webhook_owner_plan_detailed(task)
        if pro_gate is not None:
            return pro_gate
        detail = _check_webhook_endpoint_contract_detailed(task)
        if detail is not None:
            logger.warning('webhook validation failed for task %s: %s', task.pk, detail)
            return _webhook_user_facing_reason(detail)
        return None

    logger.warning('is_task_configuration_valid: unknown task type %s', task.type)
    return 'Unknown task type.'


def _is_valid_github_repo_target(target):
    if not target or target.count('/') != 1:
        return False
    owner, repo = target.split('/')
    return bool(owner.strip()) and bool(repo.strip())


def _check_github_repo_public(task) -> bool:
    return _check_github_repo_public_detailed(task) is None


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


def _check_ph_post_exists(task) -> bool:
    return _check_ph_post_exists_detailed(task) is None


def _check_ph_post_exists_detailed(task):
    ok, post_vars, reason = _resolve_ph_post_query_vars(task.target_id)
    if not ok:
        return reason

    query = f'query({ _ph_query_signature(post_vars) }) {{ post({ _ph_query_arg(post_vars) }) {{ id }} }}'
    try:
        response = requests.post(
            'https://api.producthunt.com/v2/api/graphql',
            json={'query': query, 'variables': post_vars},
            headers={
                'Authorization': f'Bearer {settings.PH_DEV_TOKEN}',
                'Content-Type':  'application/json',
            },
            timeout=10,
        )
        response.raise_for_status()
        if not response.json().get('data', {}).get('post'):
            logger.warning(
                'on_task_created: PH post %s not found (task %s)',
                task.target_id, task.pk,
            )
            return 'Product Hunt post not found. Use post slug.'
        return None
    except requests.RequestException as exc:
        logger.error('on_task_created: PH check failed for task %s: %s', task.pk, exc)
        return f'Product Hunt post check failed: {exc}'


def _resolve_ph_post_query_vars(target):
    """Return (ok, vars, reason). vars is {'postSlug': ...}."""
    raw = (target or '').strip()
    if not raw:
        return False, None, 'Product Hunt target is required.'

    if raw.startswith('http://') or raw.startswith('https://'):
        return False, None, 'Use Product Hunt post slug only (no URL).'

    if raw.isdigit():
        return False, None, 'Use Product Hunt post slug only (no numeric ID).'

    candidate = raw.strip().lower()
    if not candidate:
        return False, None, 'Product Hunt slug is required.'

    # Keep slug validation intentionally simple for now.
    if any(ch.isspace() for ch in candidate):
        return False, None, 'Product Hunt slug must not contain spaces.'

    return True, {'postSlug': candidate}, None


def _ph_query_signature(post_vars, include_cursor=False):
    base = '$postSlug: String!'
    if include_cursor:
        return f'{base}, $cursor: String'
    return base


def _ph_query_arg(post_vars):
    return 'slug: $postSlug'


def _matches_ph_user(edge, ph_user_id, ph_username):
    user = edge.get('node', {}).get('user', {})
    edge_id = (user.get('id') or '').strip()
    edge_username = (user.get('username') or '').strip().lower()

    if ph_user_id and edge_id and edge_id == ph_user_id:
        return True
    if ph_username and edge_username and edge_username == ph_username:
        return True
    return False


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
    Runs the appropriate health check for a task.
    On failure: sets hidden=True and fires a TASK_HEALTH_FAILED owner notification
    via a procrastinate background job (deduplicated — task is already hidden on
    the next feed fetch so no re-check runs).
    Returns True if healthy, False if failed.
    """
    healthy = _check_task_health(task)
    if not healthy:
        task.hidden = True
        task.save(update_fields=['hidden'])
        _schedule_health_failed_notification(task)
    return healthy


def _check_task_health(task) -> bool:
    """Returns True if the external resource is still reachable / valid."""
    try:
        if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
            response = requests.get(
                f'https://api.github.com/repos/{task.target_id}',
                headers=_github_headers(),
                timeout=10,
            )
            if response.status_code != 200:
                return False
            return not response.json().get('private', True)

        elif task.type == Task.Type.PH_COMMENT:
            ok, post_vars, _ = _resolve_ph_post_query_vars(task.target_id)
            if not ok:
                return False
            query = 'query($postSlug: String!) { post(slug: $postSlug) { id } }'
            response = requests.post(
                'https://api.producthunt.com/v2/api/graphql',
                json={'query': query, 'variables': post_vars},
                headers={
                    'Authorization': f'Bearer {settings.PH_DEV_TOKEN}',
                    'Content-Type':  'application/json',
                },
                timeout=10,
            )
            response.raise_for_status()
            return bool(response.json().get('data', {}).get('post'))

        elif task.type == Task.Type.WEBHOOK:
            if _check_webhook_owner_plan_detailed(task) is not None:
                return False
            return _check_webhook_endpoint_contract_detailed(task) is None

    except requests.RequestException as exc:
        logger.error('run_health_check: request failed for task %s: %s', task.pk, exc)
        return False

    return True


def _schedule_health_failed_notification(task):
    """Queue a procrastinate job to notify the task owner of health failure."""
    try:
        from notifications.tasks import notify_task_health_failed
        notify_task_health_failed.defer(task_id=task.pk)
    except Exception as exc:
        logger.error(
            '_schedule_health_failed_notification: failed to queue job for task %s: %s',
            task.pk, exc,
        )
        # Fallback so owner still gets in-app notification when queue is unavailable.
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
        except Exception as fallback_exc:
            logger.error(
                '_schedule_health_failed_notification: fallback notify failed for task %s: %s',
                task.pk, fallback_exc,
            )


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
        Task.Type.PH_COMMENT: 'ph',
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

