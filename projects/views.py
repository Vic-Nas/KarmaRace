# projects/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from tasks.forms import TaskForm
from .forms import ProjectCreateForm, ProjectEditForm, ProjectUrlForm, ProjectStateForm
from .models import Project
from .services import can_activate, set_project_state


@login_required
def project_create(request):
    form = ProjectCreateForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        project = form.save(commit=False)
        project.owner = request.user
        project.state = Project.State.INACTIVE
        project.save()
        return redirect('project_detail', slug=project.slug)

    return render(request, 'projects/create.html', {'form': form})


def project_detail_with_task_form(request, project, task_form=None):
    tasks = project.tasks.filter(is_deleted=False).order_by('created_at')
    state_form = ProjectStateForm(initial={'state': project.state})
    url_form = ProjectUrlForm(instance=project)
    return render(request, 'projects/detail.html', {
        'project': project,
        'tasks': tasks,
        'task_form': task_form or TaskForm(),
        'state_form': state_form,
        'url_form': url_form,
    })


@login_required
def project_detail(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    return project_detail_with_task_form(request, project)


@login_required
def project_detail_legacy(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    return redirect('project_detail', slug=project.slug)


def _activation_error_message(reason):
    mapping = {
        'no_tasks': 'Cannot activate yet: add at least one visible task.',
        'hide_or_upgrade': 'Cannot activate: unhidden Webhook tasks require Pro. Hide them or upgrade.',
        'invalid_tasks': 'Cannot activate: one or more visible tasks have invalid targets.',
    }
    return mapping.get(reason, f'Cannot activate due to: {reason}.')


@login_required
def project_update_state(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    if request.method != 'POST':
        return redirect('project_detail', slug=project.slug)

    form = ProjectStateForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Invalid state selection.')
        return redirect('project_detail', slug=project.slug)

    target_state = form.cleaned_data['state']
    if target_state == Project.State.ACTIVE:
        ok, reason = can_activate(project)
        if not ok:
            messages.error(request, _activation_error_message(reason))
            return redirect('project_detail', slug=project.slug)

        set_project_state(project, allow_activate=True)
        project.refresh_from_db()
        if project.state == Project.State.ACTIVE:
            messages.success(request, 'Project is now active.')
        else:
            messages.error(request, 'Could not activate project. Please review tasks and try again.')
        return redirect('project_detail', slug=project.slug)

    if project.state != Project.State.INACTIVE:
        from tasks.services import lock_tasks

        project.state = Project.State.INACTIVE
        project.save(update_fields=['state'])
        lock_tasks(project)
    messages.success(request, 'Project is now inactive.')
    return redirect('project_detail', slug=project.slug)


@login_required
def project_update_url(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    if request.method != 'POST':
        return redirect('project_detail', slug=project.slug)

    form = ProjectUrlForm(request.POST, instance=project)
    if form.is_valid():
        form.save()
        messages.success(request, 'Project URL updated.')
    else:
        messages.error(request, 'Could not update URL. Enter a valid URL and try again.')

    return redirect('project_detail', slug=project.slug)


@login_required
def project_edit(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    form = ProjectEditForm(
        request.POST or None,
        instance=project,
        initial={'activate': project.state == Project.State.ACTIVE},
    )

    if request.method == 'POST' and form.is_valid():
        form.save()
        wants_active = form.cleaned_data.get('activate')
        activation_error = None

        if wants_active:
            ok, reason = can_activate(project)
            if ok:
                set_project_state(project, allow_activate=True)
                project.refresh_from_db()
                if project.state != Project.State.ACTIVE:
                    activation_error = 'no_tasks'
            else:
                activation_error = reason
        else:
            if project.state == Project.State.ACTIVE:
                from tasks.services import lock_tasks

                project.state = Project.State.INACTIVE
                project.save(update_fields=['state'])
                lock_tasks(project)

        if activation_error:
            return render(request, 'projects/edit.html', {
                'form': form,
                'project': project,
                'activation_error': activation_error,
            })

        return redirect('project_detail', slug=project.slug)

    return render(request, 'projects/edit.html', {'form': form, 'project': project})


@login_required
def project_edit_legacy(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    return redirect('project_edit', slug=project.slug)