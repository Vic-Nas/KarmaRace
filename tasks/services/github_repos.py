# tasks/services/github_repos.py
"""GitHub repo collection logic (internal, complex query)."""
import logging
import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

GITHUB_REPO_CHOICES_CACHE_SECONDS = 900


def get_user_github_repo_choices_cached(user, user_token, username, force_reload=False):
    """Fetch GitHub repos available to user (with caching)."""
    cache_key = f'github_repo_choices_v4:{user.pk}'
    if not force_reload:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached, ''

    repos = []
    seen = set()
    observed_scopes = ''
    from .github import _github_headers

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
