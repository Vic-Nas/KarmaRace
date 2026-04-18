# feed/views.py
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST
from django.db.models import Sum, Value, Q
from django.db.models.functions import Coalesce

from tasks.models import Task, TaskCompletion, ReciprocityObligation
from setup.platform_rules import (
    KARMA_REWARDS_BY_TASK_TYPE,
    WEBHOOK_FAILURE_RATE_EPSILON,
    WEBHOOK_OBLIGATIONS_ENABLED,
)


def _open_obligations(user):
    if not user.is_authenticated:
        return []
    queryset = ReciprocityObligation.objects.filter(
            debtor=user,
            state=ReciprocityObligation.State.OPEN,
        )
    if not WEBHOOK_OBLIGATIONS_ENABLED:
        queryset = queryset.exclude(task_type=Task.Type.WEBHOOK)
    return list(queryset.select_related('creditor'))


def _active_lock_obligations(user, obligations):
    """Enforce lock only when at least one actionable obligation card exists."""
    if not obligations:
        return []

    candidate = _get_feed_task(
        user,
        completion='not_completed',
        archive='not_archived',
        obligations=obligations,
    )
    return obligations if candidate else []


def _feed_queryset(user, completion='not_completed', archive='not_archived', task_family='all', obligations=None):
    """Visible tasks ranked by owner karma balance (descending)."""
    qs = Task.objects.filter(is_deleted=False, hidden=False).select_related('owner')

    if user.is_authenticated:
        qs = qs.exclude(owner=user)

        if task_family == 'webhook':
            qs = qs.filter(type=Task.Type.WEBHOOK)
        elif task_family == 'not_webhook':
            qs = qs.exclude(type=Task.Type.WEBHOOK)

        if obligations:
            allowed_pairs = Q(pk__in=[])
            for item in obligations:
                allowed_pairs |= Q(owner_id=item.creditor_id, type=item.task_type)

            qs = qs.filter(allowed_pairs)
            qs = qs.exclude(archived_by=user)
            qs = qs.exclude(
                completions__tester=user,
                completions__state=TaskCompletion.State.CONFIRMED,
            )
        else:
            if archive == 'not_archived':
                qs = qs.exclude(archived_by=user)
            elif archive == 'archived':
                qs = qs.filter(archived_by=user)

            if completion == 'not_completed':
                qs = qs.exclude(
                    completions__tester=user,
                    completions__state=TaskCompletion.State.CONFIRMED,
                )
            elif completion == 'completed':
                qs = qs.filter(
                    completions__tester=user,
                    completions__state=TaskCompletion.State.CONFIRMED,
                )

    qs = qs.annotate(
        owner_balance=Coalesce(Sum('owner__karma_transactions__delta'), Value(0))
    ).order_by('-owner_balance', 'created_at')

    return qs


def _get_feed_task(user, completion='not_completed', archive='not_archived', task_family='all', obligations=None):
    """Pick first healthy task candidate from the ranked task feed."""
    from tasks.services import run_health_check

    qs = _feed_queryset(
        user,
        completion=completion,
        archive=archive,
        task_family=task_family,
        obligations=obligations,
    )

    for task in qs.iterator():
        if run_health_check(task):
            task.refresh_from_db()
            if not task.is_deleted and not task.hidden:
                return task

    return None


def _reward_for_task(task):
    try:
        return int(KARMA_REWARDS_BY_TASK_TYPE.get(task.type, 0))
    except (TypeError, ValueError):
        return 0


def _webhook_stats(task):
    if task.type != Task.Type.WEBHOOK:
        return None

    completion_qs = TaskCompletion.objects.filter(task=task)
    tried_failed = completion_qs.filter(state=TaskCompletion.State.FAILED).count()
    completed = completion_qs.filter(state=TaskCompletion.State.CONFIRMED).count()
    not_tried = (
        task.archived_by
        .exclude(task_completions__task=task)
        .exclude(id=task.owner_id)
        .distinct()
        .count()
    )
    denominator = completed + tried_failed + not_tried + WEBHOOK_FAILURE_RATE_EPSILON
    failure_rate = tried_failed / denominator

    return {
        'tried_failed': tried_failed,
        'completed': completed,
        'not_tried': not_tried,
        'failure_rate': failure_rate,
    }


def feed(request):
    completion = request.GET.get('completion') or 'not_completed'
    archive = request.GET.get('archive') or 'not_archived'
    task_family = request.GET.get('task_family') or 'all'
    checking_task_id = request.GET.get('checking_task') or ''
    obligations = _active_lock_obligations(request.user, _open_obligations(request.user))

    task = _get_feed_task(
        request.user,
        completion=completion,
        archive=archive,
        task_family=task_family,
        obligations=obligations,
    )
    completed_task_ids = set()

    if task and request.user.is_authenticated:
        completed_task_ids = set(
            TaskCompletion.objects.filter(
                tester=request.user,
                task=task,
                state=TaskCompletion.State.CONFIRMED,
            ).values_list('task_id', flat=True)
        )

    is_checking = False
    if task and request.user.is_authenticated and checking_task_id:
        try:
            target_check_id = int(checking_task_id)
        except ValueError:
            target_check_id = 0

        if target_check_id == task.id:
            is_checking = TaskCompletion.objects.filter(
                task=task,
                tester=request.user,
                state=TaskCompletion.State.PENDING,
            ).exists()

    webhook_stats = _webhook_stats(task) if task else None

    return render(request, 'feed/index.html', {
        'task': task,
        'task_reward': _reward_for_task(task) if task else '?',
        'completed_task_ids': completed_task_ids,
        'feed_empty': task is None,
        'completion': completion,
        'archive': archive,
        'task_family': task_family,
        'obligation_mode': bool(obligations),
        'open_obligations_count': len(obligations),
        'webhook_stats': webhook_stats,
        'checking_task_id': task.id if is_checking else '',
    })


def _redirect_to_feed_with_filters(request, extra_params=None):
    params = {}
    for key in ('completion', 'archive', 'task_family'):
        value = (request.POST.get(key) or '').strip()
        if value:
            params[key] = value

    if extra_params:
        params.update(extra_params)

    url = reverse('feed')
    if params:
        return redirect(f'{url}?{urlencode(params)}')
    return redirect(url)


@require_POST
def done(request, task_id):
    """Archive this task for the current user and advance the feed."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    obligations = _active_lock_obligations(request.user, _open_obligations(request.user))
    if obligations:
        messages.error(request, 'Archive is disabled while you have open obligations.')
        return _redirect_to_feed_with_filters(request)

    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id != request.user.id:
        task.archived_by.add(request.user)

    return _redirect_to_feed_with_filters(request)


@require_POST
def check(request, task_id):
    """Queue async verification for current user on a task."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    from feed.tasks import process_task_check

    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id == request.user.id:
        messages.error(request, 'You cannot check your own task.')
        return redirect('feed')

    completion, _ = TaskCompletion.objects.get_or_create(
        task=task,
        tester=request.user,
        defaults={'state': TaskCompletion.State.PENDING},
    )

    if completion.state == TaskCompletion.State.CONFIRMED:
        messages.info(request, 'Task already confirmed for you.')
        return _redirect_to_feed_with_filters(request)

    if completion.state == TaskCompletion.State.PENDING:
        messages.info(request, 'Check already in progress...')
        return _redirect_to_feed_with_filters(request, extra_params={'checking_task': str(task.pk)})

    completion.state = TaskCompletion.State.PENDING
    completion.save(update_fields=['state'])

    try:
        process_task_check.defer(task_id=task.pk, tester_id=request.user.pk)
    except Exception:
        completion.state = TaskCompletion.State.FAILED
        completion.save(update_fields=['state'])
        messages.error(request, 'Could not queue async check. Please try again.')
        return _redirect_to_feed_with_filters(request)

    messages.info(request, 'Check started. Waiting for result...')
    return _redirect_to_feed_with_filters(request, extra_params={'checking_task': str(task.pk)})


def check_status(request, task_id):
    """Return async check state for the current user and task."""
    if not request.user.is_authenticated:
        return JsonResponse({'state': 'UNAUTHENTICATED'}, status=401)

    completion = TaskCompletion.objects.filter(
        task_id=task_id,
        tester=request.user,
    ).first()
    if completion is None:
        return JsonResponse({'state': 'NOT_STARTED'})

    return JsonResponse({'state': completion.state})