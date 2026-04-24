# tasks/views.py
import json

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import TaskForm
from .models import Task
from .services import (
    on_task_unhidden, soft_delete_task,
    get_task_configuration_failure, assign_task_karma_reward,
)


@login_required
def my_tasks(request):
    tasks = Task.objects.filter(owner=request.user, is_deleted=False).order_by('-priority', '-created_at')
    return render(request, 'tasks/my_tasks.html', {'tasks': tasks})


@login_required
def slug_available(request):
    slug = (request.GET.get('slug') or '').strip()
    task_id = request.GET.get('task_id')
    if not slug:
        return JsonResponse({'available': False, 'reason': 'Slug is required.'})
    slug_field = Task._meta.get_field('slug').formfield()
    try:
        slug = slug_field.clean(slug)
    except Exception:
        return JsonResponse({'available': False, 'reason': 'Invalid slug format.'})
    qs = Task.objects.filter(owner=request.user, slug=slug)
    if task_id:
        try:
            qs = qs.exclude(pk=int(task_id))
        except (TypeError, ValueError):
            pass
    available = not qs.exists()
    return JsonResponse({'available': available, 'reason': '' if available else 'Slug already used by one of your tasks.'})


@login_required
def task_create(request):
    force_repo_reload = request.method == 'GET' and request.GET.get('reload_repos') == '1'
    form = TaskForm(request.POST or None, user=request.user, force_repo_reload=force_repo_reload)
    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        task.owner = request.user
        task.hidden = True
        task.owner_unpublished = True
        if task.type != Task.Type.WEBHOOK:
            task.webhook_secret = ''
        task.save()
        assign_task_karma_reward(task)
        return redirect('my_tasks')
    return render(request, 'tasks/edit.html', {'task': None, 'form': form, 'is_create': True})


@login_required
def task_edit(request, task_slug):
    task = get_object_or_404(Task, slug=task_slug, owner=request.user, is_deleted=False)
    force_repo_reload = request.method == 'GET' and request.GET.get('reload_repos') == '1'
    form = TaskForm(request.POST or None, instance=task, user=request.user, force_repo_reload=force_repo_reload)
    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        if task.type != Task.Type.WEBHOOK:
            task.webhook_secret = ''
        task.save()
        return redirect('my_tasks')
    return render(request, 'tasks/edit.html', {'task': task, 'form': form, 'is_create': False})


@login_required
@require_POST
def task_delete(request, task_slug):
    task = get_object_or_404(Task, slug=task_slug, owner=request.user, is_deleted=False)
    soft_delete_task(task)
    return redirect('my_tasks')


@login_required
@require_POST
def task_unpublish(request, task_slug):
    task = get_object_or_404(Task, slug=task_slug, owner=request.user, is_deleted=False)
    if not task.owner_unpublished:
        task.owner_unpublished = True
        task.hidden = True
        task.save(update_fields=['owner_unpublished', 'hidden'])
    return redirect('my_tasks')


@login_required
@require_POST
def task_publish(request, task_slug):
    task = get_object_or_404(Task, slug=task_slug, owner=request.user, is_deleted=False)
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
                'owner_unpublished', 'hidden',
                'webhook_health_success_count', 'webhook_health_failure_count',
                'health_last_result', 'health_last_failure_reason',
                'health_last_checked_at', 'health_failure_streak',
            ])
            on_task_unhidden(task)
            messages.success(request, 'Task published.')
        else:
            messages.error(request, f'Cannot publish task: {reason}')
    return redirect('my_tasks')


@login_required
@require_POST
def task_reorder(request):
    """Receive ordered list of task IDs, assign priority descending so top = highest."""
    try:
        ids = json.loads(request.body).get('ids', [])
    except (ValueError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    tasks = Task.objects.filter(owner=request.user, is_deleted=False, pk__in=ids)
    task_map = {t.pk: t for t in tasks}
    total = len(ids)
    for i, raw_id in enumerate(ids):
        try:
            pk = int(raw_id)
        except (TypeError, ValueError):
            continue
        task = task_map.get(pk)
        if task:
            task.priority = total - i
            task.save(update_fields=['priority'])

    return JsonResponse({'ok': True})
