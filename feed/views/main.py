# feed/views/main.py
"""Main feed view."""
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.http import urlencode

from setup.platform_rules import karma_reward_for_task
from tasks.check_feedback import msg
from tasks.models import Task, TaskCompletion
from .filtering import (
    SESSION_FEED_PIN_KEY, DEFAULT_COMPLETION, DEFAULT_ARCHIVE,
    load_filter_preferences, save_filter_preferences, normalize_task_types, TASK_TYPE_LABELS, ALL_TASK_TYPES,
)
from .queries import get_feed_task, get_pinned_task, webhook_stats


def feed(request):
    """Main feed view: display next task and manage filters."""
    check_result = (request.GET.get('check_result') or '').strip().upper()
    check_detail = (request.GET.get('check_detail') or '').strip()
    if check_result == TaskCompletion.State.CONFIRMED:
        messages.success(request, msg('CHECK_CONFIRMED'))
    elif check_result == TaskCompletion.State.FAILED:
        messages.error(request, check_detail or msg('CHECK_FAILED_GENERIC'))

    has_overrides = any(k in request.GET for k in ('completion', 'archive', 'task_types'))
    if has_overrides:
        completion     = request.GET.get('completion') or DEFAULT_COMPLETION
        archive        = request.GET.get('archive') or DEFAULT_ARCHIVE
        selected_types = normalize_task_types(request.GET.getlist('task_types'))
    else:
        completion, archive, selected_types = load_filter_preferences(request.user)

    checking_task_id = request.GET.get('checking_task') or ''

    if has_overrides:
        save_filter_preferences(request.user, completion, archive, selected_types)
        base = reverse('feed')
        if checking_task_id:
            return redirect(f'{base}?{urlencode({"checking_task": checking_task_id})}')
        return redirect(base)

    task = get_pinned_task(request, archive=archive, task_types=selected_types)
    if task is None:
        task = get_feed_task(request.user, completion=completion, archive=archive, task_types=selected_types)
        if request.user.is_authenticated and archive == 'not_archived':
            request.session[SESSION_FEED_PIN_KEY] = task.id if task else None
            if not task:
                request.session.pop(SESSION_FEED_PIN_KEY, None)

    completed_task_ids = set()
    if task and request.user.is_authenticated:
        completed_task_ids = set(
            TaskCompletion.objects.filter(
                tester=request.user, task=task, state=TaskCompletion.State.CONFIRMED,
            ).values_list('task_id', flat=True)
        )

    verified_emails = []
    if request.user.is_authenticated and task and task.type == Task.Type.WEBHOOK:
        verified_emails = list(request.user.verified_emails.values_list('email', flat=True).order_by('verified_at'))

    is_checking = False
    if task and request.user.is_authenticated and checking_task_id:
        try:
            cid = int(checking_task_id)
        except ValueError:
            cid = 0
        if cid == task.id:
            is_checking = TaskCompletion.objects.filter(
                task=task, tester=request.user, state=TaskCompletion.State.PENDING,
            ).exists()

    return render(request, 'feed/index.html', {
        'task':                  task,
        'task_reward':           karma_reward_for_task(task.owner_balance, task.type) if task else '?',
        'completed_task_ids':    completed_task_ids,
        'feed_empty':            task is None,
        'completion':            completion,
        'archive':               archive,
        'selected_task_types':   selected_types,
        'selected_task_types_csv': ','.join(selected_types),
        'all_task_types': [
            {'value': t, 'label': TASK_TYPE_LABELS.get(t, t.replace('_', ' ').title())}
            for t in ALL_TASK_TYPES
        ],
        'webhook_stats':         webhook_stats(task) if task else None,
        'checking_task_id':      task.id if is_checking else '',
        'verified_emails':       verified_emails,
    })
