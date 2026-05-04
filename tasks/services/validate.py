# tasks/services/validate.py
"""Task configuration validation (GitHub and Webhook checks)."""
import logging
import requests
from .github import get_public_repo
from urllib.parse import urlparse

from tasks.models import Task
from .health import _record_webhook_health_outcome, _notify_webhook_attempt

logger = logging.getLogger(__name__)


def get_task_configuration_failure(task):
    """Check if task config is valid before publishing."""
    if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
        return _check_github_repo_public_detailed(task)
    elif task.type == Task.Type.WEBHOOK:
        pro_gate = None if getattr(task.owner, 'is_pro', False) else 'Webhook tasks are Pro-only.'
        if pro_gate:
            return pro_gate
        return _check_webhook_target_format(task)
    logger.warning('get_task_configuration_failure: unknown task type %s', task.type)
    return 'Unknown task type.'


def _is_valid_github_repo_target(target):
    """Validate GitHub repo target format: owner/repo."""
    if not target or target.count('/') != 1:
        return False
    owner, repo = target.split('/')
    return bool(owner.strip()) and bool(repo.strip())


def _check_github_repo_public_detailed(task):
    """Verify GitHub repo exists and is public."""
    if not _is_valid_github_repo_target(task.target_id):
        return 'GitHub target must be owner/repo format.'
    repo, error = get_public_repo(task.target_id)
    if error == 'not_found':
        return 'GitHub repo not found. Check owner/repo spelling.'
    if error == 'private':
        return 'GitHub repo is private. Feed tasks require a public repo.'
    if error:
        logger.error('_check_github_repo_public: failed for task %s: %s', task.pk, error)
        return f'GitHub repo check failed: {error}'
    return None


def _check_webhook_target_format(task):
    """Validate webhook URL format."""
    parsed = urlparse((task.target_id or '').strip())
    if not parsed.scheme or not parsed.netloc:
        return 'Webhook URL is invalid. Use a full http/https URL.'
    if parsed.scheme not in ('http', 'https'):
        return 'Webhook URL is invalid. Use http or https.'
    return None


def _check_webhook_endpoint_contract_detailed(task):
    """Test webhook endpoint with probe request."""
    from urllib.parse import urlparse
    parsed = urlparse(task.target_id)
    if not parsed.scheme or not parsed.netloc:
        return (
            f'Webhook target is invalid. Sent: {task.target_id}; '
            'Expected: full http/https URL; Got: missing scheme or host.'
        )
    expected = '{"verified": true|false}'
    payload = {'task_slug': task.slug, 'google_email': 'probe@karmarace.com'}
    headers = {'Content-Type': 'application/json'}
    if task.webhook_secret:
        headers['Authorization'] = f'Bearer {task.webhook_secret}'

    try:
        response = requests.post(task.target_id, json=payload, headers=headers, timeout=10)
        body = response.text
        try:
            decoded = response.json()
        except ValueError:
            _record_webhook_health_outcome(task, False, 'invalid_json', 'Webhook response was non-JSON.')
            _notify_webhook_attempt(task, 'invalid_json', 'health-check', payload,
                                    {'http_status': response.status_code, 'response_body': body[:500]})
            return (
                f'Webhook endpoint contract check failed. Sent: POST {task.target_id} body={payload}; '
                f'Expected: {expected}; Got: status={response.status_code} non-JSON body={body[:300]}.'
            )

        verified = decoded.get('verified', None)
        if isinstance(verified, bool):
            _notify_webhook_attempt(task, 'verified' if verified else 'not_verified', 'health-check',
                                    payload, {'http_status': response.status_code, 'response_json': decoded})
            return None

        _record_webhook_health_outcome(task, False, 'invalid_shape',
                                       'Webhook response JSON missing boolean verified field.')
        _notify_webhook_attempt(task, 'invalid_shape', 'health-check', payload,
                                {'http_status': response.status_code, 'response_json': decoded})
        return (
            f'Webhook endpoint contract check failed. Sent: POST {task.target_id} body={payload}; '
            f'Expected: {expected}; Got: status={response.status_code} json={decoded}.'
        )
    except requests.RequestException as exc:
        _record_webhook_health_outcome(task, False, 'request_error', f'Webhook request error: {exc}')
        _notify_webhook_attempt(task, 'request_error', 'health-check', payload, {'error': str(exc)})
        return (
            f'Webhook endpoint contract check failed. Sent: POST {task.target_id} body={payload}; '
            f'Expected: {expected}; Got: request error={exc}.'
        )
    except Exception:
        logger.exception('_check_webhook_endpoint_contract_detailed: unexpected error for task %s', task.pk)
        return 'Webhook contract check failed due to an unexpected error.'