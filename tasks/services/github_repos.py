# tasks/services/github_repos.py
"""GitHub repo collection logic (internal, complex query)."""
import logging

from django.core.cache import cache
from github import Github, GithubException, UnknownObjectException

logger = logging.getLogger(__name__)

GITHUB_REPO_CHOICES_CACHE_SECONDS = 900
MAX_REPOS_PER_SOURCE = 500
MAX_PUSH_EVENT_REPOS = 40


def get_user_github_repo_choices_cached(user, user_token, username, force_reload=False):
    """Fetch GitHub repos available to user (with caching)."""
    cache_key = f'github_repo_choices_v4:{user.pk}'
    if not force_reload:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached, ''

    repos = []
    seen = set()

    def add_if_eligible(repo):
        full_name = (getattr(repo, 'full_name', '') or '').strip()
        if not full_name or full_name in seen:
            return
        if getattr(repo, 'private', True):
            return
        permissions = getattr(repo, 'permissions', None)
        if permissions and not getattr(permissions, 'push', None):
            return
        seen.add(full_name)
        repos.append((full_name, full_name))

    def collect_repos(paginated, limit=MAX_REPOS_PER_SOURCE):
        count = 0
        for repo in paginated:
            add_if_eligible(repo)
            count += 1
            if count >= limit:
                break

    try:
        gh = Github(user_token)
        gh_user = gh.get_user()
    except GithubException as exc:
        if exc.status in (401, 403):
            return [], 'Cannot load GitHub repositories. Reconnect your GitHub account in Accounts.'
        logger.warning('get_user_github_repo_choices: auth error for user %s: %s', user.pk, exc)
        return [], 'Could not load GitHub repositories right now. Click Reload repos to retry.'
    except Exception as exc:
        logger.warning('get_user_github_repo_choices: github init failed for user %s: %s', user.pk, exc)
        return [], 'Could not load GitHub repositories right now. Click Reload repos to retry.'

    try:
        collect_repos(gh_user.get_repos(type='all', sort='updated', direction='desc'))
        collect_repos(gh_user.get_repos(type='member', sort='updated', direction='desc'))
        collect_repos(gh_user.get_repos(affiliation='owner,collaborator,organization_member',
                                        sort='updated', direction='desc'))
        try:
            for org in gh_user.get_orgs():
                collect_repos(org.get_repos(type='all', sort='updated', direction='desc'))
        except GithubException as exc:
            if exc.status == 403:
                # Token lacks read:org scope — org repos unavailable, personal repos still returned.
                logger.debug('get_user_github_repo_choices: read:org not granted for user %s, skipping org repos', user.pk)
            else:
                raise
    except GithubException as exc:
        if exc.status in (401, 403):
            return [], 'Cannot load GitHub repositories. Reconnect your GitHub account in Accounts.'
        logger.warning('get_user_github_repo_choices: repo list failed for user %s: %s', user.pk, exc)

    try:
        if username:
            push_candidates = []
            seen_candidates = set()
            for event in gh.get_user(username).get_events():
                if len(push_candidates) >= MAX_PUSH_EVENT_REPOS:
                    break
                if getattr(event, 'type', '') != 'PushEvent':
                    continue
                repo_data = getattr(event, 'repo', None)
                if isinstance(repo_data, dict):
                    repo_name = (repo_data.get('name') or '').strip()
                else:
                    repo_name = (getattr(repo_data, 'name', '') or '').strip()
                if repo_name and repo_name not in seen_candidates:
                    seen_candidates.add(repo_name)
                    push_candidates.append(repo_name)

            for repo_full_name in push_candidates:
                try:
                    add_if_eligible(gh.get_repo(repo_full_name))
                except UnknownObjectException:
                    continue
    except GithubException as exc:
        logger.warning('get_user_github_repo_choices: push enrichment failed for user %s: %s', user.pk, exc)
    except Exception as exc:
        logger.warning('get_user_github_repo_choices: push enrichment unexpected for user %s: %s', user.pk, exc)

    repos.sort(key=lambda item: item[0].lower())
    if not repos:
        return [], 'No eligible public push-access repositories were discovered for this GitHub token.'

    cache.set(cache_key, repos, GITHUB_REPO_CHOICES_CACHE_SECONDS)
    return repos, ''