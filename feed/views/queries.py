# feed/views/queries.py
"""Feed query builders and data fetching."""
from django.db.models import Sum, Value, Q
from django.db.models.functions import Coalesce
from tasks.models import Task, TaskCompletion, ReciprocityObligation
from setup.platform_rules import WEBHOOK_FAILURE_RATE_EPSILON
from .filtering import normalize_task_types


def open_obligations(user):
    """Return open obligations ordered oldest first (clears debts in creation order)."""
    if not user.is_authenticated:
        return []
    return list(
        ReciprocityObligation.objects.filter(
            debtor=user, state=ReciprocityObligation.State.OPEN,
        ).order_by('created_at').select_related('creditor')
    )


def get_obligation_tasks(user, obligation):
    """
    All valid tasks for an obligation (creditor, type), difficulty-filtered.
    Falls back to lowest available if none qualify.
    """
    base_qs = (
        Task.objects.filter(is_deleted=False, hidden=False, owner_id=obligation.creditor_id, type=obligation.task_type)
        .exclude(archived_by=user)
        .exclude(completions__tester=user, completions__state=TaskCompletion.State.CONFIRMED)
        .annotate(owner_balance=Coalesce(Sum('owner__karma_transactions__delta'), Value(0)))
        .order_by('difficulty_sum', '-created_at')
    )
    tasks = list(base_qs)
    if obligation.source_difficulty is not None:
        filtered = [t for t in tasks if t.difficulty <= obligation.source_difficulty]
        if filtered:
            return filtered
    return tasks


def active_lock_obligations(user, obligations):
    """Filter obligations to those with at least one available task."""
    return [ob for ob in obligations if get_obligation_tasks(user, ob)] if obligations else []


def feed_queryset(user, completion='not_completed', archive='not_archived', task_types=None, obligations=None):
    """
    Rank tasks: owner karma desc → task priority desc → newest first.
    Priority is owner-set drag order on My Tasks page.
    """
    task_types = normalize_task_types(task_types)
    qs = Task.objects.filter(is_deleted=False, hidden=False).select_related('owner')

    if user.is_authenticated:
        qs = qs.exclude(owner=user)
        if obligations:
            allowed = Q(pk__in=[])
            for ob in obligations:
                allowed |= Q(owner_id=ob.creditor_id, type=ob.task_type)
            qs = (qs.filter(allowed)
                    .exclude(archived_by=user)
                    .exclude(completions__tester=user, completions__state=TaskCompletion.State.CONFIRMED))
        else:
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


def get_feed_task(user, completion='not_completed', archive='not_archived', task_types=None, obligations=None):
    """Get the next task from the feed."""
    return feed_queryset(user, completion=completion, archive=archive,
                         task_types=task_types, obligations=obligations).first()


def get_pinned_task(request, archive='not_archived', task_types=None, obligations=None):
    """Get the user's pinned task if it's still valid."""
    from .filtering import SESSION_FEED_PIN_KEY
    
    task_types = normalize_task_types(task_types)
    if not request.user.is_authenticated or obligations or archive != 'not_archived':
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
