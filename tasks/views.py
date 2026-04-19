# tasks/views.py
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import TaskForm
from .models import Task
from .services import on_task_unhidden, soft_delete_task
from .services import get_task_configuration_failure


@login_required
def my_tasks(request):
    tasks = Task.objects.filter(owner=request.user, is_deleted=False).order_by('-created_at')
    return render(request, 'tasks/my_tasks.html', {'tasks': tasks})


@login_required
def task_create(request):
    form = TaskForm(request.POST or None)

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
    form = TaskForm(request.POST or None, instance=task)

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
            task.save(update_fields=['owner_unpublished', 'hidden'])
            on_task_unhidden(task)
            messages.success(request, 'Task published.')
        else:
            messages.error(request, f'Cannot publish task: {reason}')
    return redirect('my_tasks')