# tasks/views.py
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
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
    return JsonResponse({
        'available': available,
        'reason': '' if available else 'Slug already used by one of your tasks.',
    })


@login_required
def task_create(request):
    force_repo_reload = request.method == 'GET' and request.GET.get('reload_repos') == '1'
    form = TaskForm(
        request.POST or None,
        user=request.user,
        force_repo_reload=force_repo_reload,
    )

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
def task_edit(request, task_slug):
    task = get_object_or_404(Task, slug=task_slug, owner=request.user, is_deleted=False)
    force_repo_reload = request.method == 'GET' and request.GET.get('reload_repos') == '1'
    form = TaskForm(
        request.POST or None,
        instance=task,
        user=request.user,
        force_repo_reload=force_repo_reload,
    )

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
def task_health_check(request, task_slug):
    task = get_object_or_404(Task, slug=task_slug, owner=request.user, is_deleted=False)

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
        messages.error(task.webhook_owner_reason_summary or 'Health check failed.')

    if task.hidden and task.owner_unpublished:
        messages.warning(request, 'Task was auto-unpublished due to unhealthy webhook ratio.')

    return redirect('my_tasks')