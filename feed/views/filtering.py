# feed/views/filtering.py
"""Feed filter preferences and task type normalization."""
from tasks.models import Task


SESSION_FEED_PIN_KEY = 'feed_pinned_task_id'
DEFAULT_COMPLETION   = 'not_completed'
DEFAULT_ARCHIVE      = 'not_archived'
PREF_FEED_COMPLETION  = 'feed_filter_completion'
PREF_FEED_ARCHIVE     = 'feed_filter_archive'
PREF_FEED_TASK_TYPES  = 'feed_filter_task_types'

ALL_TASK_TYPES = [Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK, Task.Type.WEBHOOK]
TASK_TYPE_LABELS = {
    Task.Type.GITHUB_STAR: 'GitHub Star',
    Task.Type.GITHUB_FORK: 'GitHub Fork',
    Task.Type.WEBHOOK:     'Webhook',
}


def normalize_task_types(values):
    """Normalize task types list, validating each entry."""
    valid, normalized, seen = set(ALL_TASK_TYPES), [], set()
    for raw in values or []:
        for item in str(raw or '').split(','):
            t = item.strip()
            if t and t in valid and t not in seen:
                seen.add(t)
                normalized.append(t)
    return normalized or list(ALL_TASK_TYPES)


def load_filter_preferences(user):
    """Load user's saved feed filter preferences or return defaults."""
    if not user.is_authenticated:
        return DEFAULT_COMPLETION, DEFAULT_ARCHIVE, list(ALL_TASK_TYPES)
    from accounts.models import UserPreference
    prefs = dict(
        UserPreference.objects.filter(
            user=user, key__in=[PREF_FEED_COMPLETION, PREF_FEED_ARCHIVE, PREF_FEED_TASK_TYPES],
        ).values_list('key', 'value')
    )
    return (
        prefs.get(PREF_FEED_COMPLETION) or DEFAULT_COMPLETION,
        prefs.get(PREF_FEED_ARCHIVE) or DEFAULT_ARCHIVE,
        normalize_task_types((prefs.get(PREF_FEED_TASK_TYPES) or '').split(',')),
    )


def save_filter_preferences(user, completion, archive, task_types):
    """Save user's feed filter preferences."""
    if not user.is_authenticated:
        return
    from accounts.models import UserPreference
    for key, value in {
        PREF_FEED_COMPLETION: completion,
        PREF_FEED_ARCHIVE:    archive,
        PREF_FEED_TASK_TYPES: ','.join(normalize_task_types(task_types)),
    }.items():
        UserPreference.objects.update_or_create(user=user, key=key, defaults={'value': value})
