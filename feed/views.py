# feed/views.py
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.http import urlencode
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from tasks.models import Task, TaskCompletion


def _expire_stale_cards_for_user(user):
    """Auto-archive cards older than 1 day when tester made no decision."""
    if not user.is_authenticated:
        return

    cutoff = timezone.now() - timezone.timedelta(days=1)

    stale_qs = (
        Task.objects
        .filter(is_deleted=False, hidden=False, created_at__lt=cutoff)
        .exclude(owner=user)
        .exclude(archived_by=user)
        .exclude(completions__tester=user)
        .distinct()
    )

    stale_ids = list(stale_qs.values_list('id', flat=True))
    if stale_ids:
        user.archived_tasks.add(*stale_ids)


def _feed_queryset(user, completion='not_completed', archive='not_archived', promise='with_promise'):
    """Visible tasks ranked by owner karma balance (descending)."""
    qs = Task.objects.filter(is_deleted=False, hidden=False).select_related('owner')

    if user.is_authenticated:
        qs = qs.exclude(owner=user)

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

        # Promise dimension: standard verifiable tasks vs webhook tasks.
        if promise == 'with_promise':
            qs = qs.exclude(type=Task.Type.WEBHOOK)
        elif promise == 'without_promise':
            qs = qs.filter(type=Task.Type.WEBHOOK)

    qs = qs.annotate(
        owner_balance=Coalesce(Sum('owner__karma_transactions__delta'), Value(0))
    ).order_by('-owner_balance', 'created_at')

    return qs


def _get_feed_task(user, completion='not_completed', archive='not_archived', promise='with_promise'):
    """Pick first healthy task candidate from the ranked task feed."""
    from tasks.services import run_health_check

    qs = _feed_queryset(user, completion=completion, archive=archive, promise=promise)

    for task in qs.iterator():
        if run_health_check(task):
            task.refresh_from_db()
            if not task.is_deleted and not task.hidden:
                return task

    return None


def _karma_rewards_by_type():
    from accounts.models import PlatformConfig

    reward_keys = {
        'GITHUB_STAR': 'karma_reward_github_star',
        'GITHUB_FORK': 'karma_reward_github_fork',
        'PH_COMMENT': 'karma_reward_ph',
        'WEBHOOK': 'karma_reward_webhook',
    }
    configs = PlatformConfig.objects.filter(key__in=reward_keys.values())
    config_map = {c.key: c.value for c in configs}
    return {task_type: config_map.get(cfg_key, '?') for task_type, cfg_key in reward_keys.items()}


def _reward_for_task(task):
    rewards = _karma_rewards_by_type()
    try:
        return int(rewards.get(task.type, 0))
    except (TypeError, ValueError):
        return 0


def feed(request):
    _expire_stale_cards_for_user(request.user)

    completion = request.GET.get('completion') or 'not_completed'
    archive = request.GET.get('archive') or 'not_archived'
    promise = request.GET.get('promise') or 'with_promise'

    task = _get_feed_task(
        request.user,
        completion=completion,
        archive=archive,
        promise=promise,
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

    karma_rewards = _karma_rewards_by_type()

    return render(request, 'feed/index.html', {
        'task': task,
        'task_reward': karma_rewards.get(task.type, '?') if task else '?',
        'completed_task_ids': completed_task_ids,
        'feed_empty': task is None,
        'completion': completion,
        'archive': archive,
        'promise': promise,
    })


def _redirect_to_feed_with_filters(request):
    params = {}
    for key in ('completion', 'archive', 'promise'):
        value = (request.POST.get(key) or '').strip()
        if value:
            params[key] = value

    url = reverse('feed')
    if params:
        return redirect(f'{url}?{urlencode(params)}')
    return redirect(url)


@require_POST
def done(request, task_id):
    """Archive this task for the current user and advance the feed."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id != request.user.id:
        task.archived_by.add(request.user)

    return _redirect_to_feed_with_filters(request)


@require_POST
def check(request, task_id):
    """Run verification for current user on a task and record completion state."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    from karma.models import KarmaTransaction
    from karma.services import credit_karma, debit_karma
    from tasks.services import verify_task_with_details

    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id == request.user.id:
        messages.error(request, 'You cannot check your own task.')
        return redirect('feed')

    completion, _ = TaskCompletion.objects.get_or_create(
        task=task,
        tester=request.user,
        defaults={'state': TaskCompletion.State.PENDING},
    )

    task.tried_count += 1

    ok, detail = verify_task_with_details(task, request.user)
    if ok:
        if completion.state != TaskCompletion.State.CONFIRMED:
            completion.state = TaskCompletion.State.CONFIRMED
            completion.save(update_fields=['state'])

            reward = _reward_for_task(task)
            if reward > 0:
                credit_karma(
                    user=request.user,
                    delta=reward,
                    reason=KarmaTransaction.Reason.TASK_EARNED,
                    related_object_id=task.pk,
                )
                debit_karma(
                    user=task.owner,
                    delta=reward,
                    reason=KarmaTransaction.Reason.TASK_COST,
                    related_object_id=task.pk,
                )

            task.succeed_count += 1
            messages.success(request, detail or 'Task check passed. Reward applied.')
        else:
            messages.info(request, 'Task already confirmed for you.')
    else:
        completion.state = TaskCompletion.State.FAILED
        completion.save(update_fields=['state'])
        messages.error(request, detail or 'Task check failed. Please verify target/action and try again.')

    task.save(update_fields=['tried_count', 'succeed_count'])
    return _redirect_to_feed_with_filters(request)