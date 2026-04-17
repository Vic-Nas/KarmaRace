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
    dispatch = {
        Task.Type.GITHUB_STAR: verify_github,
        Task.Type.GITHUB_FORK: verify_github,
        Task.Type.PH_COMMENT:  verify_ph,
        Task.Type.WEBHOOK:     verify_webhook,
    }
    verifier = dispatch.get(task.type)
    if verifier is None:
        logger.error('verify_task: unknown task type %s', task.type)
        return False
    return verifier(task, tester)


# ---------------------------------------------------------------------------
# Platform verifiers
# ---------------------------------------------------------------------------

def verify_github(task, tester) -> bool:
    """
    Check star or fork via GitHub API using server credentials.
    task.target_id must be the repo full name, e.g. "owner/repo".
    tester must have a linked GitHub account with platform_username set.
    """
    try:
        linked = tester.linked_accounts.get(platform='github')
    except tester.linked_accounts.model.DoesNotExist:
        logger.info('verify_github: tester %s has no linked GitHub account', tester.pk)
        return False

    username = linked.platform_username
    repo     = task.target_id

    try:
        if task.type == Task.Type.GITHUB_STAR:
            url      = f'https://api.github.com/repos/{repo}/stargazers/{username}'
            headers  = _github_headers()
            response = requests.get(url, headers=headers, timeout=10)
            return response.status_code == 204  # GitHub returns 204 when the relationship exists
        else:
            url      = f'https://api.github.com/repos/{repo}/forks'
            headers  = _github_headers()
            response = requests.get(url, headers=headers, params={'per_page': 100}, timeout=10)
            response.raise_for_status()
            forks = response.json()
            return any(f.get('owner', {}).get('login', '').lower() == username.lower() for f in forks)

    except requests.RequestException as exc:
        logger.error('verify_github: request failed for task %s: %s', task.pk, exc)
        return False


def verify_ph(task, tester) -> bool:
    """
    Check Product Hunt upvote or comment presence via PH GraphQL API.
    Uses tester's stored access_token for user-scoped queries.
    task.target_id must be the PH post numeric ID.
    """
    try:
        linked = tester.linked_accounts.get(platform='producthunt')
    except tester.linked_accounts.model.DoesNotExist:
        logger.info('verify_ph: tester %s has no linked Product Hunt account', tester.pk)
        return False

    access_token = linked.access_token
    post_id      = task.target_id

    query = """
    query($postId: ID!) {
      post(id: $postId) {
        isVoted
        comments(first: 100) {
          edges {
            node {
              user { id }
            }
          }
        }
      }
    }
    """

    try:
        response = requests.post(
            'https://api.producthunt.com/v2/api/graphql',
            json={'query': query, 'variables': {'postId': post_id}},
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type':  'application/json',
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        post = data.get('data', {}).get('post')
        if not post:
            logger.warning('verify_ph: post %s not found', post_id)
            return False

        if task.type == Task.Type.PH_COMMENT:
            ph_user_id = linked.platform_id
            comments   = post.get('comments', {}).get('edges', [])
            return any(
                edge.get('node', {}).get('user', {}).get('id') == ph_user_id
                for edge in comments
            )

        return bool(post.get('isVoted'))

    except requests.RequestException as exc:
        logger.error('verify_ph: request failed for task %s: %s', task.pk, exc)
        return False


def verify_webhook(task, tester) -> bool:
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
        return response.json().get('verified', False)
    except requests.RequestException as exc:
        logger.error('verify_webhook: request failed for task %s: %s', task.pk, exc)
        return False


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------

def soft_delete_task(task):
    """
    Soft-delete a task:
    - Sets is_deleted=True.
    - Auto-fails all PENDING completions for this task.
    - Re-evaluates the parent project state (may go INACTIVE if no tasks remain).
    """
    from projects.services import set_project_state

    task.is_deleted = True
    task.save(update_fields=['is_deleted'])

    TaskCompletion.objects.filter(
        task=task,
        state=TaskCompletion.State.PENDING,
    ).update(state=TaskCompletion.State.FAILED)

    set_project_state(task.project)


# ---------------------------------------------------------------------------
# Creation hook
# ---------------------------------------------------------------------------

def on_task_created(task):
    """
    Called after a new task is saved.
    - Clears project.archived_by (new task unarchive rule).
    - Runs upfront validity checks appropriate to the task type.
    - Re-evaluates project state.
    """
    from projects.services import set_project_state

    # Unarchive: new task makes the project worth revisiting for all users.
    task.project.archived_by.clear()

    # Upfront validity checks (best-effort; failures are logged, not raised).
    _run_creation_validity_check(task)

    set_project_state(task.project)


def _run_creation_validity_check(task):
    """
    Ping external resources at task creation time to catch obvious mistakes early.
    Failures are logged but do not block task creation.
    """
    if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
        _check_github_repo_public(task)
    elif task.type == Task.Type.PH_COMMENT:
        _check_ph_post_exists(task)
    elif task.type == Task.Type.WEBHOOK:
        _check_webhook_domain_reachable(task)


def _check_github_repo_public(task):
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
        else:
            logger.warning(
                'on_task_created: GitHub repo %s not found (task %s, status %s)',
                task.target_id, task.pk, response.status_code,
            )
    except requests.RequestException as exc:
        logger.error('on_task_created: GitHub check failed for task %s: %s', task.pk, exc)


def _check_ph_post_exists(task):
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
    except requests.RequestException as exc:
        logger.error('on_task_created: PH check failed for task %s: %s', task.pk, exc)


def _check_webhook_domain_reachable(task):
    """HEAD (fallback GET) the root domain of the webhook endpoint."""
    from urllib.parse import urlparse
    parsed = urlparse(task.target_id)
    root   = f'{parsed.scheme}://{parsed.netloc}/'
    try:
        response = requests.head(root, timeout=10, allow_redirects=True)
        if response.status_code >= 500:
            logger.warning(
                'on_task_created: webhook domain %s returned %s (task %s)',
                root, response.status_code, task.pk,
            )
    except requests.RequestException:
        try:
            response = requests.get(root, timeout=10, allow_redirects=True)
            if response.status_code >= 500:
                logger.warning(
                    'on_task_created: webhook domain %s returned %s (task %s)',
                    root, response.status_code, task.pk,
                )
        except requests.RequestException as exc:
            logger.warning(
                'on_task_created: webhook domain %s unreachable (task %s): %s',
                root, task.pk, exc,
            )


# ---------------------------------------------------------------------------
# Unhide hook
# ---------------------------------------------------------------------------

def on_task_unhidden(task):
    """
    Called when a task's hidden flag is set back to False.
    Selectively removes the project from archived_by for users who have NOT
    already confirmed this task — giving them a reason to revisit.
    Then re-evaluates project state (may go ACTIVE again).
    """
    from projects.services import set_project_state

    completed_user_ids = TaskCompletion.objects.filter(
        task=task,
        state=TaskCompletion.State.CONFIRMED,
    ).values_list('tester_id', flat=True)

    users_to_unarchive = task.project.archived_by.exclude(id__in=completed_user_ids)
    task.project.archived_by.remove(*users_to_unarchive)

    set_project_state(task.project)


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _github_headers() -> dict:
    token = getattr(settings, 'GITHUB_TOKEN', None)
    headers = {'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers