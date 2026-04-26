# tasks/services.py
import logging
import requests
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache

from django.conf import settings

from tasks.models import Task, TaskCompletion, ReciprocityObligation
from tasks.check_feedback import msg
from setup.platform_rules import (
    WEBHOOK_FAILURE_RATE_EPSILON,
    WEBHOOK_BAD_CHECK_RATIO_THRESHOLD,
    WEBHOOK_BAD_CHECK_MIN_CALLS,
    WEBHOOK_HEALTH_CHECK_RATE_LIMIT_SECONDS,
    karma_reward_for_task,
)

logger = logging.getLogger(__name__)

HEALTH_HIDE_THRESHOLD = 2
GITHUB_REPO_CHOICES_CACHE_SECONDS = 900


# ---------------------------------------------------------------------------
# Verification dispatcher
# ---------------------------------------------------------------------------

def verify_task_with_details(task, tester, google_email=''):
    dispatch = {
        Task.Type.GITHUB_STAR: verify_github_with_details,
        Task.Type.GITHUB_FORK: verify_github_with_details,
        Task.Type.WEBHOOK:     verify_webhook_with_details,
    }
    verifier = dispatch.get(task.type)
    if verifier is None:
        logger.error('verify_task: unknown task type %s', task.type)
        return False, msg('UNKNOWN_TASK_TYPE')
    if task.type == Task.Type.WEBHOOK:
        return verifier(task, tester, google_email=google_email)
    return verifier(task, tester)


# ---------------------------------------------------------------------------
# Platform verifiers
# ---------------------------------------------------------------------------

def verify_github_with_details(task, tester):
    username, user_token = _get_github_identity(tester)
    if not username:
        return False, msg('GITHUB_LINK_REQUIRED')

    repo = task.target_id
    if not _is_valid_github_repo_target(repo):
        return False, msg('TARGET_OWNER_REPO_REQUIRED')

    try:
        if not user_token:
            return False, msg('GITHUB_TOKEN_RECONNECT')

        if task.type == Task.Type.GITHUB_STAR:
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


def verify_webhook_with_details(task, tester, google_email=''):
    import hmac, hashlib
    email = (google_email or '').strip()
    sig = hmac.new(
        (task.webhook_secret or '').encode(),
        f"{task.slug}:{email}".encode(),
        hashlib.sha256,
    ).hexdigest()
    headers = {'Authorization': f'Bearer {task.webhook_secret}'} if task.webhook_secret else {}
    sent_payload = {'task_slug': task.slug, 'google_email': email, 'signature': sig}

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
            return True, msg('WEBHOOK_VERIFIED')

        _record_webhook_health_outcome(task, False, 'not_verified', 'Webhook response contained verified=false.')
        notify_owner('not_verified', {'http_status': response.status_code, 'response_json': body})
        return False, msg('WEBHOOK_NOT_VERIFIED')

    except requests.RequestException as exc:
        logger.error('verify_webhook: request failed for task %s: %s', task.pk, exc)
        _record_webhook_health_outcome(task, False, 'request_error', f'Webhook request error: {exc}')
        notify_owner('request_error', {'error': str(exc)})
        return False, msg('WEBHOOK_REQUEST_FAILED')
    except ValueError:
        _record_webhook_health_outcome(task, False, 'invalid_json', 'Webhook response was non-JSON.')
        notify_owner('invalid_json', {'response': 'non-json response'})
        return False, msg('WEBHOOK_BAD_JSON')


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------

def soft_delete_task(task):
    task.is_deleted = True
    task.save(update_fields=['is_deleted'])
    TaskCompletion.objects.filter(
        task=task,
        state=TaskCompletion.State.PENDING,
    ).update(state=TaskCompletion.State.FAILED, result_detail=msg('ARCHIVED_DURING_CHECK'))


@transaction.atomic
def settle_or_create_obligation(actor, counterparty, task_type, completed_task):
    """Settle existing debt first; otherwise create reverse obligation.
    Obligations apply to all task types including WEBHOOK.
    """
    if actor.pk == counterparty.pk:
        return None

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
# Reward computation — called at task creation time
# ---------------------------------------------------------------------------

def assign_task_karma_reward(task):
    """Compute and persist karma_reward based on owner's current balance."""
    from karma.services import get_balance
    owner_karma = get_balance(task.owner)
    task.karma_reward = karma_reward_for_task(owner_karma, task.type)
    task.save(update_fields=['karma_reward'])


# ---------------------------------------------------------------------------
# Configuration check (runs at publish time)
# ---------------------------------------------------------------------------

def get_task_configuration_failure(task):
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
                return 'GitHub repo is private. Feed tasks require a public repo.'
            return None
        elif response.status_code == 404:
            return 'GitHub repo not found. Check owner/repo spelling.'
        return f'GitHub API returned status {response.status_code} while checking repo.'
    except requests.RequestException as exc:
        logger.error('on_task_created: GitHub check failed for task %s: %s', task.pk, exc)
        return f'GitHub repo check failed: {exc}'


def _check_webhook_endpoint_contract_detailed(task):
    from urllib.parse import urlparse
    parsed = urlparse(task.target_id)
    if not parsed.scheme or not parsed.netloc:
        return (
            f'Webhook target is invalid. Sent: {task.target_id}; '
            'Expected: full http/https URL; Got: missing scheme or host.'
        )
    expected = '{"verified": true|false}'
    payload = {'task_slug': task.slug, 'google_email': 'probe@karmarace.com', 'signature': 'probe'}
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
            _record_webhook_health_outcome(
                task, bool(verified),
                'verified' if verified else 'not_verified',
                'Manual webhook health check response parsed successfully.',
            )
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


def _check_webhook_target_format(task):
    from urllib.parse import urlparse
    parsed = urlparse((task.target_id or '').strip())
    if not parsed.scheme or not parsed.netloc:
        return 'Webhook URL is invalid. Use a full http/https URL.'
    if parsed.scheme not in ('http', 'https'):
        return 'Webhook URL is invalid. Use http or https.'
    return None


# ---------------------------------------------------------------------------
# Unhide hook
# ---------------------------------------------------------------------------

def on_task_unhidden(task):
    completed_user_ids = TaskCompletion.objects.filter(
        task=task, state=TaskCompletion.State.CONFIRMED,
    ).values_list('tester_id', flat=True)
    users_to_unarchive = task.archived_by.exclude(id__in=completed_user_ids)
    if users_to_unarchive:
        task.archived_by.remove(*users_to_unarchive)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def run_health_check(task) -> bool:
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

    should_hide = task.health_failure_streak >= HEALTH_HIDE_THRESHOLD
    transitioned_to_hidden = should_hide and not task.hidden
    if transitioned_to_hidden:
        task.hidden = True
        update_fields.append('hidden')

    task.save(update_fields=update_fields)

    if transitioned_to_hidden:
        _notify_health_failed(task)

    return False


def _notify_health_failed(task):
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


def _check_task_health_with_reason(task):
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
        logger.error('run_health_check: request failed for task %s: %s', task.pk, exc)
        return False, f'External request failed: {exc}'

    return False, 'Unknown task type for health check.'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_github_identity(tester):
    username = ''
    access_token = ''

    linked = tester.linked_accounts.filter(platform='github').first()
    if linked:
        username = (linked.platform_username or '').strip()
        access_token = (linked.access_token or '').strip()

    try:
        from allauth.socialaccount.models import SocialAccount, SocialToken
        social = SocialAccount.objects.filter(user=tester, provider='github').first()
        if social:
            if not username:
                username = (
                    social.extra_data.get('login') or social.extra_data.get('username') or ''
                ).strip()
            if not access_token:
                token = SocialToken.objects.filter(account=social).order_by('-pk').first()
                access_token = (token.token if token else '') or ''
    except Exception as exc:
        logger.warning('verify_github: allauth fallback failed for tester %s: %s', tester.pk, exc)

    return username, access_token


def get_user_github_repo_choices(user):
    return get_user_github_repo_choices_cached(user, force_reload=False)


def get_user_github_repo_choices_cached(user, force_reload=False):
    username, user_token = _get_github_identity(user)
    if not user_token:
        return [], 'Cannot load GitHub repositories. Link your GitHub account in Accounts.'

    cache_key = f'github_repo_choices_v4:{user.pk}'
    if not force_reload:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached, ''

    repos = []
    seen = set()
    observed_scopes = ''

    def add_if_eligible(repo):
        full_name = (repo.get('full_name') or '').strip()
        if not full_name or full_name in seen:
            return
        if repo.get('private'):
            return
        if not (repo.get('permissions') or {}).get('push'):
            return
        seen.add(full_name)
        repos.append((full_name, full_name))

    def collect_user_repos(extra_params):
        nonlocal observed_scopes
        page = 1
        while page <= 5:
            params = {'sort': 'updated', 'direction': 'desc', 'per_page': 100, 'page': page}
            params.update(extra_params or {})
            response = requests.get(
                'https://api.github.com/user/repos',
                headers=_github_headers(token_override=user_token),
                params=params, timeout=10,
            )
            observed_scopes = observed_scopes or (response.headers.get('X-OAuth-Scopes') or '')
            if response.status_code in (401, 403):
                return response, 'auth'
            if response.status_code == 422:
                return response, 'unprocessable'
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            for repo in data:
                add_if_eligible(repo)
            if len(data) < 100:
                break
            page += 1
        return None, 'ok'

    def collect_org_repos(org_login):
        page = 1
        while page <= 5:
            response = requests.get(
                f'https://api.github.com/orgs/{org_login}/repos',
                headers=_github_headers(token_override=user_token),
                params={'type': 'all', 'sort': 'updated', 'direction': 'desc', 'per_page': 100, 'page': page},
                timeout=10,
            )
            if response.status_code in (401, 403, 404, 422):
                return
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            for repo in data:
                add_if_eligible(repo)
            if len(data) < 100:
                break
            page += 1

    def collect_orgs_from(url, extract_login):
        page = 1
        found = set()
        while page <= 5:
            response = requests.get(
                url, headers=_github_headers(token_override=user_token),
                params={'per_page': 100, 'page': page}, timeout=10,
            )
            if response.status_code in (401, 403, 404, 422):
                return found
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or not data:
                break
            for item in data:
                login = (extract_login(item) or '').strip()
                if login:
                    found.add(login)
            if len(data) < 100:
                break
            page += 1
        return found

    def collect_recent_push_event_repos(max_candidates=40):
        if not username:
            return []
        found = []
        seen_candidates = set()
        page = 1
        while page <= 5 and len(found) < max_candidates:
            response = requests.get(
                f'https://api.github.com/users/{username}/events/public',
                headers=_github_headers(token_override=user_token),
                params={'per_page': 100, 'page': page}, timeout=10,
            )
            if response.status_code in (401, 403, 404, 422):
                return found
            response.raise_for_status()
            events = response.json()
            if not isinstance(events, list) or not events:
                break
            for event in events:
                if event.get('type') != 'PushEvent':
                    continue
                repo_name = ((event.get('repo') or {}).get('name') or '').strip()
                if not repo_name or repo_name in seen_candidates:
                    continue
                seen_candidates.add(repo_name)
                found.append(repo_name)
                if len(found) >= max_candidates:
                    break
            if len(events) < 100:
                break
            page += 1
        return found

    def collect_repo_details(repo_full_name):
        response = requests.get(
            f'https://api.github.com/repos/{repo_full_name}',
            headers=_github_headers(token_override=user_token), timeout=10,
        )
        if response.status_code in (401, 403, 404, 422):
            return
        response.raise_for_status()
        add_if_eligible(response.json())

    try:
        for params in ({'type': 'all'}, {'type': 'member'}, {'affiliation': 'owner,collaborator,organization_member'}):
            resp, mode = collect_user_repos(params)
            if mode == 'auth':
                return [], 'Cannot load GitHub repositories. Reconnect your GitHub account in Accounts.'
            if mode == 'unprocessable':
                logger.warning('get_user_github_repo_choices: query returned 422 for user %s', user.pk)

        org_logins = set()
        org_logins.update(collect_orgs_from('https://api.github.com/user/orgs', lambda i: i.get('login')))
        org_logins.update(collect_orgs_from(
            'https://api.github.com/user/memberships/orgs',
            lambda i: (i.get('organization') or {}).get('login'),
        ))
        if username:
            org_logins.update(collect_orgs_from(
                f'https://api.github.com/users/{username}/orgs', lambda i: i.get('login'),
            ))

        for org_login in sorted(org_logins):
            collect_org_repos(org_login)

        try:
            for repo_full_name in collect_recent_push_event_repos():
                collect_repo_details(repo_full_name)
        except requests.RequestException as exc:
            logger.warning('get_user_github_repo_choices: push enrichment failed for user %s: %s', user.pk, exc)

        scopes = {s.strip() for s in (observed_scopes or '').split(',') if s.strip()}
        if 'read:org' not in scopes and 'repo' not in scopes:
            logger.warning('get_user_github_repo_choices: limited org visibility for user %s (scopes=%s)',
                           user.pk, observed_scopes)
    except requests.RequestException as exc:
        logger.warning('get_user_github_repo_choices: failed for user %s: %s', user.pk, exc)
        return [], 'Could not load GitHub repositories right now. Click Reload repos to retry.'

    repos.sort(key=lambda item: item[0].lower())
    if not repos:
        return [], 'No eligible public push-access repositories were discovered for this GitHub token.'

    cache.set(cache_key, repos, GITHUB_REPO_CHOICES_CACHE_SECONDS)
    return repos, ''


def _github_headers(token_override=None) -> dict:
    token = token_override or getattr(settings, 'GITHUB_TOKEN', None)
    headers = {'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _notify_webhook_attempt(task, status, phase, sent_payload, detail, tester=None):
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


def can_run_manual_health_check(task):
    if task.health_last_checked_at is None:
        return True, 0
    delta = timezone.now() - task.health_last_checked_at
    seconds = int(delta.total_seconds())
    wait = int(WEBHOOK_HEALTH_CHECK_RATE_LIMIT_SECONDS) - seconds
    if wait > 0:
        return False, wait
    return True, 0


def _record_webhook_health_outcome(task, is_success, result, reason):
    if task.type != Task.Type.WEBHOOK:
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
