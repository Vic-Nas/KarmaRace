# feed/views/queries.py
"""Feed query builders and data fetching."""
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from tasks.models import Task, TaskCompletion
from setup.platform_rules import WEBHOOK_FAILURE_RATE_EPSILON
from .filtering import normalize_task_types


def feed_queryset(user, completion='not_completed', archive='not_archived', task_types=None):
    """Rank tasks: owner karma desc → task priority desc → newest first."""
    task_types = normalize_task_types(task_types)
    qs = Task.objects.filter(is_deleted=False, hidden=False).select_related('owner')

    if user.is_authenticated:
        qs = qs.exclude(owner=user)
        if archive == 'not_archived':
            qs = qs.exclude(archived_by=user)
        elif archive == 'archived':
            qs = qs.filter(archived_by=user)
        if completion == 'not_completed':
            qs = qs.exclude(completions__tester=user, completions__state=TaskCompletion.State.CONFIRMED)
        elif completion == 'completed':
            qs = qs.filter(completions__tester=user, completions__state=TaskCompletion.State.CONFIRMED)
        qs = qs.filter(type__in=task_types)
    else:
        qs = qs.filter(type__in=task_types)

    return qs.annotate(
        owner_balance=Coalesce(Sum('owner__karma_transactions__delta'), Value(0)),
    ).order_by('-owner_balance', '-priority', '-created_at')


def get_feed_task(user, completion='not_completed', archive='not_archived', task_types=None):
    """Get the next task from the feed."""
    return feed_queryset(user, completion=completion, archive=archive, task_types=task_types).first()


def get_pinned_task(request, archive='not_archived', task_types=None):
    """Get the user's pinned task if it's still valid."""
    from .filtering import SESSION_FEED_PIN_KEY

    task_types = normalize_task_types(task_types)
    if not request.user.is_authenticated or archive != 'not_archived':
        return None
    pinned_id = request.session.get(SESSION_FEED_PIN_KEY)
    if not pinned_id:
        return None
    task = Task.objects.filter(pk=pinned_id, is_deleted=False, hidden=False).select_related('owner').annotate(
        owner_balance=Coalesce(Sum('owner__karma_transactions__delta'), Value(0)),
    ).first()
    if not task or task.owner_id == request.user.id:
        request.session.pop(SESSION_FEED_PIN_KEY, None)
        return None
    if task.archived_by.filter(pk=request.user.pk).exists() or task.type not in task_types:
        request.session.pop(SESSION_FEED_PIN_KEY, None)
        return None
    return task


def webhook_stats(task):
    """Get webhook completion stats for a task."""
    if task.type != Task.Type.WEBHOOK:
        return None
    cqs = TaskCompletion.objects.filter(task=task)
    tried_failed = cqs.filter(state=TaskCompletion.State.FAILED).count()
    completed    = cqs.filter(state=TaskCompletion.State.CONFIRMED).count()
    not_tried    = (task.archived_by.exclude(task_completions__task=task)
                    .exclude(id=task.owner_id).distinct().count())
    denom = completed + tried_failed + not_tried + WEBHOOK_FAILURE_RATE_EPSILON
    return {
        'tried_failed': tried_failed, 'completed': completed, 'not_tried': not_tried,
        'failure_rate_percent': int(round(tried_failed / denom * 100)),
    }
