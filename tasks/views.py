# tasks/views.py
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import TaskForm
from .models import Task
from .services import on_task_unhidden, soft_delete_task
from .services import get_task_configuration_failure
from .services import run_health_check, can_run_manual_health_check


@login_required
def my_tasks(request):
    tasks = Task.objects.filter(owner=request.user, is_deleted=False).order_by('-created_at')
    return render(request, 'tasks/my_tasks.html', {'tasks': tasks})


@login_required
def task_create(request):
    form = TaskForm(request.POST or None, user=request.user)

    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        task.owner = request.user
        task.hidden = True
        task.owner_unpublished = True  # stays hidden until owner explicitly publishes
        if task.type != Task.Type.WEBHOOK:
            task.webhook_secret = ''
        task.save()
        # Validation runs at publish time, not here.
        return redirect('my_tasks')

    return render(request, 'tasks/edit.html', {
        'task': None,
        'form': form,
        'is_create': True,
    })


@login_required
def task_edit(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)
    form = TaskForm(request.POST or None, instance=task, user=request.user)

    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        if task.type != Task.Type.WEBHOOK:
            task.webhook_secret = ''
        task.save()
        return redirect('my_tasks')

    return render(request, 'tasks/edit.html', {
        'task': task,
        'form': form,
        'is_create': False,
    })


@login_required
@require_POST
def task_delete(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)
    soft_delete_task(task)
    return redirect('my_tasks')


@login_required
@require_POST
def task_unpublish(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)
    if not task.owner_unpublished:
        task.owner_unpublished = True
        task.hidden = True
        task.save(update_fields=['owner_unpublished', 'hidden'])
    return redirect('my_tasks')


@login_required
@require_POST
def task_publish(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)
    if task.owner_unpublished or task.hidden:
        reason = get_task_configuration_failure(task)
        if reason is None:
            task.owner_unpublished = False
            task.hidden = False
            task.webhook_health_success_count = 0
            task.webhook_health_failure_count = 0
            task.health_last_result = ''
            task.health_last_failure_reason = ''
            task.health_last_checked_at = None
            task.health_failure_streak = 0
            task.save(update_fields=[
                'owner_unpublished',
                'hidden',
                'webhook_health_success_count',
                'webhook_health_failure_count',
                'health_last_result',
                'health_last_failure_reason',
                'health_last_checked_at',
                'health_failure_streak',
            ])
            on_task_unhidden(task)
            messages.success(request, 'Task published.')
        else:
            messages.error(request, f'Cannot publish task: {reason}')
    return redirect('my_tasks')


@login_required
@require_POST
def task_health_check(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)

    if task.type != Task.Type.WEBHOOK:
        messages.info(request, 'Manual health checks are currently available only for webhook tasks.')
        return redirect('my_tasks')

    allowed, wait_seconds = can_run_manual_health_check(task)
    if not allowed:
        messages.warning(request, f'Health check is rate-limited. Try again in {wait_seconds}s.')
        return redirect('my_tasks')

    ok = run_health_check(task)
    task.refresh_from_db(fields=[
        'health_last_checked_at',
        'health_last_result',
        'health_last_failure_reason',
        'hidden',
        'owner_unpublished',
    ])

    if ok:
        messages.success(request, 'Health check passed.')
    else:
        messages.error(request, task.health_last_failure_reason or 'Health check failed.')

    if task.hidden and task.owner_unpublished:
        messages.warning(request, 'Task was auto-unpublished due to unhealthy webhook ratio.')

    return redirect('my_tasks')