"""Task health checks and webhook health outcome tracking."""
import logging
import requests
from django.utils import timezone

from tasks.models import Task
from setup.platform_rules import (
    WEBHOOK_FAILURE_RATE_EPSILON,
    WEBHOOK_BAD_CHECK_RATIO_THRESHOLD,
    WEBHOOK_BAD_CHECK_MIN_CALLS,
    WEBHOOK_HEALTH_CHECK_RATE_LIMIT_SECONDS,
    GITHUB_HEALTH_HIDE_STREAK_THRESHOLD,
)

logger = logging.getLogger(__name__)


def run_health_check(task) -> bool:
    """Run health check for task (GitHub repo or Webhook endpoint)."""
    healthy, reason = _check_task_health_with_reason(task)

    if task.type == Task.Type.WEBHOOK:
        if not healthy and reason and not task.health_last_failure_reason:
            task.health_last_failure_reason = reason
            task.save(update_fields=['health_last_failure_reason'])
        return healthy

    update_fields = ['health_last_checked_at']
    task.health_last_checked_at = timezone.now()

    if healthy:
        if task.health_failure_streak != 0:
            task.health_failure_streak = 0
            update_fields.append('health_failure_streak')
        if task.health_last_failure_reason:
            task.health_last_failure_reason = ''
            update_fields.append('health_last_failure_reason')
        task.save(update_fields=update_fields)
        return True

    task.health_failure_streak += 1
    task.health_last_failure_reason = reason or 'Health check failed.'
    update_fields.extend(['health_failure_streak', 'health_last_failure_reason'])

    should_hide = task.health_failure_streak >= GITHUB_HEALTH_HIDE_STREAK_THRESHOLD
    transitioned_to_hidden = should_hide and not task.hidden
    if transitioned_to_hidden:
        task.hidden = True
        update_fields.append('hidden')

    task.save(update_fields=update_fields)

    if transitioned_to_hidden:
        _notify_health_failed(task)

    return False


def can_run_manual_health_check(task):
    """Check if manual health check is allowed (rate-limited)."""
    if task.health_last_checked_at is None:
        return True, 0
    delta = timezone.now() - task.health_last_checked_at
    seconds = int(delta.total_seconds())
    wait = int(WEBHOOK_HEALTH_CHECK_RATE_LIMIT_SECONDS) - seconds
    if wait > 0:
        return False, wait
    return True, 0


def _record_webhook_health_outcome(task, is_success, result, reason):
    """Record webhook health check outcome and auto-unpublish if needed.

    Only request_error and invalid_json count as health failures —
    not_verified just means the user hasn't completed the task yet.
    """
    if task.type != Task.Type.WEBHOOK:
        return

    # not_verified is not an endpoint health signal — skip health accounting entirely.
    if result == 'not_verified':
        return

    update_fields = ['health_last_checked_at', 'health_last_result', 'health_last_failure_reason']
    task.health_last_checked_at = timezone.now()
    task.health_last_result = (result or '')[:64]
    task.health_last_failure_reason = reason or ''

    if is_success:
        task.webhook_health_success_count += 1
        update_fields.append('webhook_health_success_count')
    else:
        task.webhook_health_failure_count += 1
        update_fields.append('webhook_health_failure_count')

    total = task.webhook_health_success_count + task.webhook_health_failure_count
    bad_ratio = (
        float(task.webhook_health_failure_count) / float(total + WEBHOOK_FAILURE_RATE_EPSILON)
    ) if total > 0 else 0.0

    should_auto_unpublish = (
        total >= int(WEBHOOK_BAD_CHECK_MIN_CALLS)
        and bad_ratio >= float(WEBHOOK_BAD_CHECK_RATIO_THRESHOLD)
    )
    transitioned = should_auto_unpublish and not task.hidden
    if should_auto_unpublish:
        task.hidden = True
        task.owner_unpublished = True
        update_fields.extend(['hidden', 'owner_unpublished'])

    task.save(update_fields=list(dict.fromkeys(update_fields)))

    if transitioned:
        _notify_health_failed(task)


def _notify_health_failed(task):
    """Notify task owner when health check fails and task is hidden."""
    try:
        from notifications.models import Notification
        from notifications.services import notify
        notify(
            user=task.owner,
            event=Notification.Event.TASK_HEALTH_FAILED,
            payload={
                'task_id': task.pk, 'task_type': task.type, 'target_id': task.target_id,
                'owner_id': task.owner_id,
                'webhook_health_success_count': task.webhook_health_success_count,
                'webhook_health_failure_count': task.webhook_health_failure_count,
                'health_last_result': task.health_last_result,
                'health_last_failure_reason': task.health_last_failure_reason,
            },
        )
    except Exception as exc:
        logger.error('_notify_health_failed: failed for task %s: %s', task.pk, exc)


def _notify_webhook_attempt(task, status, phase, sent_payload, detail, tester=None):
    """Notify task owner of webhook verification attempt."""
    try:
        from notifications.models import Notification
        from notifications.services import notify
        payload = {
            'task_id': task.pk, 'task_type': task.type, 'target_id': task.target_id,
            'phase': phase, 'status': status, 'sent_payload': sent_payload, 'detail': detail,
        }
        if tester is not None:
            payload['tester_id'] = tester.pk
            payload['tester_username'] = getattr(tester, 'username', '')
        notify(user=task.owner, event=Notification.Event.WEBHOOK_CHECK, payload=payload)
    except Exception as exc:
        logger.warning('webhook notification emit failed for task %s: %s', task.pk, exc)


def _check_task_health_with_reason(task):
    """Check task health and return status + reason."""
    try:
        if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
            from .github import _github_headers
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
            from .validate import _check_webhook_target_format, _check_webhook_endpoint_contract_detailed
            if not getattr(task.owner, 'is_pro', False):
                return False, 'Webhook tasks are Pro-only.'
            format_reason = _check_webhook_target_format(task)
            if format_reason:
                return False, format_reason
            webhook_reason = _check_webhook_endpoint_contract_detailed(task)
            if webhook_reason is None:
                return True, ''
            return False, webhook_reason

    except requests.RequestException as exc:
        logger.error('_check_task_health: request failed for task %s: %s', task.pk, exc)
        return False, f'External request failed: {exc}'

    return False, 'Unknown task type for health check.'
