# feed/views.py
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from tasks.models import Task, TaskCompletion


def _feed_queryset(user, include_archived=False, include_completed=False):
    """Visible tasks ranked by owner karma balance (descending)."""
    qs = Task.objects.filter(is_deleted=False, hidden=False).select_related('owner')

    if user.is_authenticated:
        qs = qs.exclude(owner=user)
        if not include_archived:
            qs = qs.exclude(archived_by=user)
        if not include_completed:
            qs = qs.exclude(
                completions__tester=user,
                completions__state=TaskCompletion.State.CONFIRMED,
            )

    qs = qs.annotate(
        owner_balance=Coalesce(Sum('owner__karma_transactions__delta'), Value(0))
    ).order_by('-owner_balance', 'created_at')

    return qs


def _get_feed_task(user, include_archived=False, include_completed=False):
    """Pick first healthy task candidate from the ranked task feed."""
    from tasks.services import run_health_check

    qs = _feed_queryset(user, include_archived=include_archived, include_completed=include_completed)

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
    include_archived = request.GET.get('include_archived') == '1'
    include_completed = request.GET.get('include_completed') == '1'

    task = _get_feed_task(
        request.user,
        include_archived=include_archived,
        include_completed=include_completed,
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
        'include_archived': include_archived,
        'include_completed': include_completed,
    })


@require_POST
def done(request, task_id):
    """Archive this task for the current user and advance the feed."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id != request.user.id:
        task.archived_by.add(request.user)

    return redirect('feed')


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
    return redirect('feed')