# feed/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from tasks.models import Task, TaskCompletion


def _feed_queryset(user):
    """Visible tasks ranked by owner karma balance (descending)."""
    qs = Task.objects.filter(is_deleted=False, hidden=False).select_related('owner')

    if user.is_authenticated:
        qs = qs.exclude(owner=user).exclude(archived_by=user)

    qs = qs.annotate(
        owner_balance=Coalesce(Sum('owner__karma_transactions__delta'), Value(0))
    ).order_by('-owner_balance', 'created_at')

    return qs


def _get_feed_task(user):
    """Pick first healthy task candidate from the ranked task feed."""
    from tasks.services import run_health_check

    qs = _feed_queryset(user)

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


def feed(request):
    task = _get_feed_task(request.user)
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