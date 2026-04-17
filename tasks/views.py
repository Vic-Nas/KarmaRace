# tasks/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TaskForm
from .models import Task
from .services import on_task_created, on_task_unhidden, soft_delete_task, is_task_configuration_valid


@login_required
def task_create(request):
    form = TaskForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        task.owner = request.user
        if task.type != Task.Type.WEBHOOK:
            task.webhook_secret = ''
        task.save()
        on_task_created(task)
        return redirect('feed')

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
                task.hidden = False
                task.save(update_fields=['hidden'])
                on_task_unhidden(task)
        else:
            if not task.hidden:
                task.hidden = True
                task.save(update_fields=['hidden'])

        return redirect('feed')

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
    return redirect('feed')