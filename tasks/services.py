# tasks/services.py
import logging
import requests

from django.conf import settings

from tasks.models import Task, TaskCompletion

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
    try:
        linked = tester.linked_accounts.get(platform='github')
    except tester.linked_accounts.model.DoesNotExist:
        logger.info('verify_github: tester %s has no linked GitHub account', tester.pk)
        return False, 'Your GitHub account is not linked.'

    username = linked.platform_username
    repo     = task.target_id

    if not _is_valid_github_repo_target(repo):
        return False, 'Target must be in owner/repo format.'

    try:
        if task.type == Task.Type.GITHUB_STAR:
            url      = f'https://api.github.com/repos/{repo}/stargazers/{username}'
            response = requests.get(url, headers=_github_headers(), timeout=10)
            if response.status_code == 204:
                return True, 'Verified GitHub star.'
            if response.status_code == 404:
                return False, 'Star not found. Ensure your GitHub user starred this public repo.'
            return False, f'GitHub returned status {response.status_code} while checking star.'

        else:
            # Paginate through all forks until we find the tester's or exhaust pages.
            url = f'https://api.github.com/repos/{repo}/forks'
            params = {'per_page': 100, 'page': 1}
            while True:
                response = requests.get(url, headers=_github_headers(), params=params, timeout=10)
                response.raise_for_status()
                forks = response.json()
                if not forks:
                    return False, 'Fork not found. Ensure your GitHub user forked this public repo.'
                if any(f.get('owner', {}).get('login', '').lower() == username.lower() for f in forks):
                    return True, 'Verified GitHub fork.'
                if len(forks) < 100:
                    return False, 'Fork not found. Ensure your GitHub user forked this public repo.'
                params['page'] += 1

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
    task.target_id must be the PH post numeric ID.

    Either an upvote (isVoted) or a comment by the tester passes.
    Paginates through all comments using GraphQL cursor-based pagination.
    """
    try:
        linked = tester.linked_accounts.get(platform='producthunt')
    except tester.linked_accounts.model.DoesNotExist:
        logger.info('verify_ph: tester %s has no linked Product Hunt account', tester.pk)
        return False, 'Your Product Hunt account is not linked.'

    access_token = linked.access_token
    ph_user_id   = linked.platform_id
    post_id      = task.target_id

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type':  'application/json',
    }

    # First check isVoted — single cheap query, no pagination needed.
    voted_query = """
    query($postId: ID!) {
      post(id: $postId) {
        isVoted
      }
    }
    """
    try:
        response = requests.post(
            'https://api.producthunt.com/v2/api/graphql',
            json={'query': voted_query, 'variables': {'postId': post_id}},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        post = data.get('data', {}).get('post')
        if not post:
            logger.warning('verify_ph: post %s not found', post_id)
            return False, 'Product Hunt post not found. Check post ID.'
        if post.get('isVoted'):
            return True, 'Verified Product Hunt upvote.'
    except requests.RequestException as exc:
        logger.error('verify_ph: vote check failed for task %s: %s', task.pk, exc)
        return False, f'Product Hunt vote check failed: {exc}'

    # isVoted is False — check comments with cursor-based pagination.
    comments_query = """
    query($postId: ID!, $cursor: String) {
      post(id: $postId) {
        comments(first: 100, after: $cursor) {
          edges {
            node {
              user { id }
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """
    cursor = None
    try:
        while True:
            response = requests.post(
                'https://api.producthunt.com/v2/api/graphql',
                json={
                    'query': comments_query,
                    'variables': {'postId': post_id, 'cursor': cursor},
                },
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            data     = response.json()
            comments = data.get('data', {}).get('post', {}).get('comments', {})
            edges    = comments.get('edges', [])

            if any(
                edge.get('node', {}).get('user', {}).get('id') == ph_user_id
                for edge in edges
            ):
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
    POST {"task_id": ..., "platform_username": ...} to owner endpoint.
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

    try:
        response = requests.post(
            task.target_id,
            json={'task_id': task.pk, 'platform_username': platform_username},
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
            f'Sent: {{"task_id": {task.pk}, "platform_username": "{platform_username}"}}; '
            f'Expected: {{"verified": true}}; Got: {body}'
        )
    except requests.RequestException as exc:
        logger.error('verify_webhook: request failed for task %s: %s', task.pk, exc)
        return False, (
            'Webhook request failed. '
            f'Sent: {{"task_id": {task.pk}, "platform_username": "{platform_username}"}}; '
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
        return _check_webhook_domain_reachable_detailed(task)

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
    query = 'query($id: ID!) { post(id: $id) { id } }'
    try:
        response = requests.post(
            'https://api.producthunt.com/v2/api/graphql',
            json={'query': query, 'variables': {'id': task.target_id}},
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
            return 'Product Hunt post not found. Check post ID.'
        return None
    except requests.RequestException as exc:
        logger.error('on_task_created: PH check failed for task %s: %s', task.pk, exc)
        return f'Product Hunt post check failed: {exc}'


def _check_webhook_domain_reachable(task) -> bool:
    return _check_webhook_domain_reachable_detailed(task) is None


def _check_webhook_domain_reachable_detailed(task):
    """HEAD (fallback GET) the root domain of the webhook endpoint."""
    from urllib.parse import urlparse
    parsed = urlparse(task.target_id)
    if not parsed.scheme or not parsed.netloc:
        return 'Webhook target must be a valid URL (including http/https).'
    root   = f'{parsed.scheme}://{parsed.netloc}/'
    try:
        response = requests.head(root, timeout=10, allow_redirects=True)
        if response.status_code >= 500:
            logger.warning(
                'on_task_created: webhook domain %s returned %s (task %s)',
                root, response.status_code, task.pk,
            )
            return f'Webhook host is reachable but returned status {response.status_code}.'
        return None
    except requests.RequestException:
        try:
            response = requests.get(root, timeout=10, allow_redirects=True)
            if response.status_code >= 500:
                logger.warning(
                    'on_task_created: webhook domain %s returned %s (task %s)',
                    root, response.status_code, task.pk,
                )
                return f'Webhook host is reachable but returned status {response.status_code}.'
            return None
        except requests.RequestException as exc:
            logger.warning(
                'on_task_created: webhook domain %s unreachable (task %s): %s',
                root, task.pk, exc,
            )
            return f'Webhook host is unreachable: {exc}'


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
            query = 'query($id: ID!) { post(id: $id) { id } }'
            response = requests.post(
                'https://api.producthunt.com/v2/api/graphql',
                json={'query': query, 'variables': {'id': task.target_id}},
                headers={
                    'Authorization': f'Bearer {settings.PH_DEV_TOKEN}',
                    'Content-Type':  'application/json',
                },
                timeout=10,
            )
            response.raise_for_status()
            return bool(response.json().get('data', {}).get('post'))

        elif task.type == Task.Type.WEBHOOK:
            from urllib.parse import urlparse
            parsed = urlparse(task.target_id)
            root   = f'{parsed.scheme}://{parsed.netloc}/'
            try:
                response = requests.head(root, timeout=10, allow_redirects=True)
            except requests.RequestException:
                response = requests.get(root, timeout=10, allow_redirects=True)
            return response.status_code < 500

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

def _github_headers() -> dict:
    token = getattr(settings, 'GITHUB_TOKEN', None)
    headers = {'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers

