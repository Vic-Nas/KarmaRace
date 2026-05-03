# tasks/services/verify.py
"""Task verification: GitHub and Webhook checks."""
import logging
import requests
from github import Github, GithubException, UnknownObjectException

from tasks.models import Task
from tasks.check_feedback import msg
from .github import _get_github_identity
from .health import _record_webhook_health_outcome, _notify_webhook_attempt

logger = logging.getLogger(__name__)


def verify_github_with_details(task, tester):
    """Verify GitHub star or fork completion. Returns (ok, detail, result_code)."""
    username, user_token = _get_github_identity(tester)
    if not username:
        return False, msg('GITHUB_LINK_REQUIRED'), None
    if not user_token:
        return False, msg('GITHUB_TOKEN_RECONNECT'), None

    repo = task.target_id
    from .validate import _is_valid_github_repo_target
    if not _is_valid_github_repo_target(repo):
        return False, msg('TARGET_OWNER_REPO_REQUIRED'), None

    try:
        gh = Github(user_token)
        gh_user = gh.get_user()

        if task.type == Task.Type.GITHUB_STAR:
            gh_repo = gh.get_repo(repo)
            if gh_user.has_in_starred(gh_repo):
                return True, msg('GITHUB_STAR_VERIFIED'), 'verified'
            return False, msg('GITHUB_STAR_NOT_FOUND', username=username), 'not_verified'

        else:  # GITHUB_FORK
            _, repo_name = repo.split('/', 1)
            try:
                fork = gh_user.get_repo(repo_name)
                if fork.fork:
                    return True, msg('GITHUB_FORK_VERIFIED'), 'verified'
            except UnknownObjectException:
                pass
            return False, msg('GITHUB_FORK_NOT_FOUND', username=username), 'not_verified'

    except GithubException as exc:
        if exc.status in (401, 403):
            return False, msg('GITHUB_TOKEN_INVALID'), 'not_verified'
        logger.error('verify_github: API error for task %s: %s', task.pk, exc)
        return False, msg('GITHUB_REQUEST_FAILED', error=exc), 'request_error'
    except Exception as exc:
        logger.error('verify_github: unexpected error for task %s: %s', task.pk, exc)
        return False, msg('GITHUB_REQUEST_FAILED', error=exc), 'request_error'


def verify_webhook_with_details(task, tester, google_email=''):
    """Verify webhook task completion. Returns (ok, detail, result_code)."""
    email = (google_email or '').strip()
    headers = {'Authorization': f'Bearer {task.webhook_secret}'} if task.webhook_secret else {}
    sent_payload = {'task_slug': task.slug, 'google_email': email}

    def notify_owner(status, detail):
        _notify_webhook_attempt(
            task=task, status=status, phase='check',
            sent_payload=sent_payload, detail=detail, tester=tester,
        )

    try:
        response = requests.post(task.target_id, json=sent_payload, headers=headers, timeout=10)
        response.raise_for_status()
        body = response.json()
        verified = body.get('verified', False)

        if verified:
            _record_webhook_health_outcome(task, True, 'verified', 'Webhook response contained verified=true.')
            notify_owner('verified', {'http_status': response.status_code, 'response_json': body})
            return True, msg('WEBHOOK_VERIFIED'), 'verified'

        _record_webhook_health_outcome(task, False, 'not_verified', 'Webhook response contained verified=false.')
        notify_owner('not_verified', {'http_status': response.status_code, 'response_json': body})
        return False, msg('WEBHOOK_NOT_VERIFIED'), 'not_verified'

    except requests.RequestException as exc:
        logger.error('verify_webhook: request failed for task %s: %s', task.pk, exc)
        _record_webhook_health_outcome(task, False, 'request_error', f'Webhook request error: {exc}')
        notify_owner('request_error', {'error': str(exc)})
        return False, msg('WEBHOOK_REQUEST_FAILED'), 'request_error'
    except ValueError:
        _record_webhook_health_outcome(task, False, 'invalid_json', 'Webhook response was non-JSON.')
        notify_owner('invalid_json', {'response': 'non-json response'})
        return False, msg('WEBHOOK_BAD_JSON'), 'invalid_json'
