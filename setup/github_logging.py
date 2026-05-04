# setup/github_logging.py
"""
Custom logging handler that opens a GitHub issue for each unique error.

Deduplication: the issue title contains a short SHA-256 signature derived
from the sanitised traceback.  Before creating an issue the handler searches
for open issues with that signature so multiple workers never file duplicates.

User-data scrubbing
-------------------
* File paths are reduced to the portion starting at the project root.
* Any token that looks like an e-mail address is replaced with <email>.
* Any token that looks like a bearer / API token is replaced with <token>.
"""

import hashlib
import logging
import re
import traceback

_SENSITIVE_PATTERNS = [
    (re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'), '<email>'),
    (re.compile(r'(?i)(bearer\s+|token[=:\s]+)[a-zA-Z0-9\-_\.]{16,}'), r'\1<token>'),
    (re.compile(r'(?i)(secret[=:\s]+|password[=:\s]+|api_?key[=:\s]+)[^\s,\'"]+'), r'\1<redacted>'),
]

# Trim absolute paths to something relative to the project root so they don't
# leak server directory structure.
_PATH_RE = re.compile(r'File ".*?/(karmarace/[^"]+)"')


def _sanitise(text: str) -> str:
    text = _PATH_RE.sub(r'File "\1"', text)
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _signature(sanitised_tb: str) -> str:
    """8-char hex digest — short enough for a title, unique enough for dedup."""
    return hashlib.sha256(sanitised_tb.encode()).hexdigest()[:8]


class GitHubIssueHandler(logging.Handler):
    """
    Logging handler that files GitHub issues for ERROR-level (and above) log
    records that include a traceback.

    Configuration (all read from Django settings):
        GITHUB_TOKEN       — personal access token with repo:issues write scope
        GITHUB_ERROR_REPO  — 'owner/repo' string, e.g. 'acme/karmarace'
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._gh = None   # lazy-initialised
        self._repo = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_repo(self):
        if self._repo is not None:
            return self._repo
        try:
            from django.conf import settings
            from github import Github
            token = getattr(settings, 'GITHUB_TOKEN', '')
            repo_name = getattr(settings, 'GITHUB_ERROR_REPO', '')
            if not token or not repo_name:
                return None
            self._gh = Github(token)
            self._repo = self._gh.get_repo(repo_name)
        except Exception:
            pass
        return self._repo

    # ------------------------------------------------------------------
    # logging.Handler interface
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord):
        try:
            if record.exc_info and record.exc_info[1]:
                raw_tb = ''.join(traceback.format_exception(*record.exc_info))
                clean_tb = _sanitise(raw_tb)
            else:
                clean_tb = _sanitise(record.getMessage())
            sig = _signature(clean_tb)

            from setup.models import FiredError
            _, created = FiredError.objects.get_or_create(signature=sig)
            if not created:
                return

            repo = self._get_repo()
            if repo is None:
                return

            title = f'[{sig}] {record.name}: {_sanitise(record.getMessage())[:120]}'
            body = (
                f'**Logger**: `{record.name}`  \n'
                f'**Level**: {record.levelname}  \n'
                f'**Signature**: `{sig}`\n\n'
                f'```\n{clean_tb}\n```\n\n'
                f'> Auto-filed by `GitHubIssueHandler`. '
                f'User-identifying data has been scrubbed.'
            )

            try:
                bug_label = repo.get_label('bug')
            except Exception:
                bug_label = None

            kwargs = {'title': title, 'body': body}
            if bug_label:
                kwargs['labels'] = [bug_label]

            issue = repo.create_issue(**kwargs)
            FiredError.objects.filter(signature=sig).update(github_issue_url=issue.html_url)

        except Exception:
            self.handleError(record)