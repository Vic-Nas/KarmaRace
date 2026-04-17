# tasks/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from projects.models import Project
from .forms import TaskForm
from .models import Task
from .services import on_task_created, on_task_unhidden, soft_delete_task, is_task_configuration_valid


@login_required
def task_create(request, project_slug):
    project = get_object_or_404(Project, slug=project_slug, owner=request.user)

    if request.method == 'POST':
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.project = project
            task.save()
            on_task_created(task)
            return redirect('project_detail', slug=project.slug)
        # Fall through to detail view re-render with errors
        from projects.views import project_detail_with_task_form
        return project_detail_with_task_form(request, project, form)

    return redirect('project_detail', slug=project.slug)


@login_required
def task_edit(request, project_slug, task_pk):
    project = get_object_or_404(Project, slug=project_slug, owner=request.user)
    task = get_object_or_404(Task, pk=task_pk, project=project, is_deleted=False)

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

        from projects.services import set_project_state
        set_project_state(project)
        return redirect('project_detail', slug=project.slug)

    return render(request, 'tasks/edit.html', {
        'project': project,
        'task': task,
        'form': form,
    })


@login_required
def task_delete(request, project_slug, task_pk):
    project = get_object_or_404(Project, slug=project_slug, owner=request.user)
    task = get_object_or_404(Task, pk=task_pk, project=project, is_deleted=False)

    if request.method == 'POST':
        soft_delete_task(task)
    return redirect('project_detail', slug=project.slug)