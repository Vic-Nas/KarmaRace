# tasks/services/github.py
"""GitHub integration utilities: authentication, repo choices, API helpers."""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_github_identity(tester):
    """Get GitHub username and access token from linked account or allauth."""
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
        logger.warning('_get_github_identity: allauth fallback failed for tester %s: %s', tester.pk, exc)

    return username, access_token


def _github_headers(token_override=None) -> dict:
    """Build GitHub API request headers."""
    token = token_override or getattr(settings, 'GITHUB_TOKEN', None)
    headers = {'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def get_user_github_repo_choices(user):
    """Get cached GitHub repo choices for user (no force reload)."""
    return get_user_github_repo_choices_cached(user, force_reload=False)


def get_user_github_repo_choices_cached(user, force_reload=False):
    """Fetch GitHub repos available to user (with caching)."""
    username, user_token = _get_github_identity(user)
    if not user_token:
        return [], 'Cannot load GitHub repositories. Link your GitHub account in Accounts.'

    from .github_repos import get_user_github_repo_choices_cached as _collect_repos
    return _collect_repos(user, user_token, username, force_reload)
