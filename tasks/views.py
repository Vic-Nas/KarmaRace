# tasks/views.py
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import TaskForm
from .models import Task
from .services import on_task_created, on_task_unhidden, soft_delete_task, is_task_configuration_valid
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
        if task.type != Task.Type.WEBHOOK:
            task.webhook_secret = ''
        task.save()

        if task.type == Task.Type.WEBHOOK and not request.user.is_pro:
            task.hidden = True
            task.save(update_fields=['hidden'])
            messages.error(request, 'Webhook tasks are Pro-only and cannot be published on your current plan.')

        on_task_created(task)
        return redirect('my_tasks')

    return render(request, 'tasks/edit.html', {
        'task': None,
        'form': form,
        'is_create': True,
    })


@login_required
def task_edit(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)

    was_hidden = task.hidden
    form = TaskForm(request.POST or None, instance=task)

    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        if task.type != Task.Type.WEBHOOK:
            task.webhook_secret = ''
        task.save()

        if is_task_configuration_valid(task):
            if was_hidden and task.hidden:
                if task.type == Task.Type.WEBHOOK and not request.user.is_pro:
                    messages.error(request, 'Webhook tasks are Pro-only and cannot be published on your current plan.')
                else:
                    task.hidden = False
                    task.save(update_fields=['hidden'])
                    on_task_unhidden(task)
        else:
            if not task.hidden:
                task.hidden = True
                task.save(update_fields=['hidden'])

        return redirect('my_tasks')

    return render(request, 'tasks/edit.html', {
        'task': task,
        'form': form,
        'is_create': False,
    })


@login_required
def task_delete(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)

    if request.method == 'POST':
        soft_delete_task(task)
    return redirect('my_tasks')


@login_required
@require_POST
def task_unpublish(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)
    if not task.hidden:
        task.hidden = True
        task.save(update_fields=['hidden'])
    return redirect('my_tasks')


@login_required
@require_POST
def task_publish(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk, owner=request.user, is_deleted=False)
    if task.hidden:
        if task.type == Task.Type.WEBHOOK and not request.user.is_pro:
            messages.error(request, 'Cannot publish task: Webhook tasks are Pro-only.')
            return redirect('my_tasks')

        reason = get_task_configuration_failure(task)
        if reason is None:
            task.hidden = False
            task.save(update_fields=['hidden'])
            on_task_unhidden(task)
            messages.success(request, 'Task published.')
        else:
            messages.error(request, f'Cannot publish task: {reason}')
    return redirect('my_tasks')