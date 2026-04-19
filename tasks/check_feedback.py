MESSAGES = {
    'UNKNOWN_TASK_TYPE': 'Unknown task type.',
    'TASK_TEMPORARILY_UNAVAILABLE': 'This task is temporarily unavailable. Please try again later.',
    'TARGET_OWNER_REPO_REQUIRED': 'Target must be in owner/repo format.',
    'GITHUB_LINK_REQUIRED': 'Connect your GitHub account in Accounts before checking GitHub tasks.',
    'GITHUB_TOKEN_RECONNECT': 'Linked GitHub token is missing. Reconnect your GitHub account and try again.',
    'GITHUB_TOKEN_INVALID': 'GitHub token is invalid or missing scope. Reconnect your GitHub account and try again.',
    'GITHUB_STAR_VERIFIED': 'Verified GitHub star.',
    'GITHUB_FORK_VERIFIED': 'Verified GitHub fork.',
    'GITHUB_STAR_NOT_FOUND': "We couldn't verify the star for @{username} yet. Please star the public repo with your linked GitHub account, wait a minute, then press Check again.",
    'GITHUB_FORK_NOT_FOUND': "We couldn't verify a fork for @{username} yet. Please fork the repo with your linked GitHub account, wait a minute, then press Check again.",
    'GITHUB_STATUS_STAR': 'GitHub returned status {status} while checking star.',
    'GITHUB_STATUS_FORK': 'GitHub returned status {status} while checking fork.',
    'GITHUB_REQUEST_FAILED': 'GitHub verification request failed: {error}',
    'WEBHOOK_VERIFIED': 'Webhook verified successfully.',
    'WEBHOOK_NOT_VERIFIED': 'Webhook return was invalid for verification. Sent: {sent}; Expected: {expected}; Got preview: {got}',
    'WEBHOOK_REQUEST_FAILED': 'Webhook request failed. Sent: {sent}; Expected: {expected}; Error: {error}',
    'WEBHOOK_BAD_JSON': 'Webhook response is not valid JSON. Expected {expected}.',
    'CHECK_CONFIRMED': 'Check confirmed. Karma transferred.',
    'CHECK_FAILED_GENERIC': 'Check failed. Please verify the task requirements and try again.',
    'CHECK_TIMEOUT': 'Verification timed out. Please retry.',
    'CHECK_TIMEOUT_WORKER_HINT': 'Verification timed out. Please retry. If this is local/dev, ensure a procrastinate worker is running.',
    'CHECK_IN_PROGRESS': 'Check already in progress...',
    'CHECK_STARTED': 'Check started. Waiting for result...',
    'ALREADY_CONFIRMED': 'Task already confirmed for you.',
    'QUEUE_UNAVAILABLE_CONFIRMED': 'Queue unavailable, but check confirmed immediately.',
    'QUEUE_UNAVAILABLE_FAILED': 'Queue unavailable, and check failed.',
    'QUEUE_FAILED': 'Could not queue async check. Please try again.',
    'ARCHIVE_DISABLED_OBLIGATIONS': 'Archive is disabled while you have open obligations.',
    'ARCHIVED_DURING_CHECK': 'Task was archived or unpublished before verification completed.',
}


def msg(key, **kwargs):
    text = MESSAGES.get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text