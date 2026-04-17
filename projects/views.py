# projects/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from tasks.forms import TaskForm
from .forms import ProjectCreateForm, ProjectEditForm
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
        return redirect('project_detail', pk=project.pk)

    return render(request, 'projects/create.html', {'form': form})


def project_detail_with_task_form(request, project, task_form=None):
    tasks = project.tasks.filter(is_deleted=False).order_by('created_at')
    return render(request, 'projects/detail.html', {
        'project': project,
        'tasks': tasks,
        'task_form': task_form or TaskForm(),
    })


@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    return project_detail_with_task_form(request, project)


@login_required
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
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
                set_project_state(project)
                project.refresh_from_db()
                if project.state != Project.State.ACTIVE:
                    activation_error = 'no_tasks'
            else:
                activation_error = reason
        else:
            if project.state == Project.State.ACTIVE:
                project.state = Project.State.INACTIVE
                project.save(update_fields=['state'])

        if activation_error:
            return render(request, 'projects/edit.html', {
                'form': form,
                'project': project,
                'activation_error': activation_error,
            })
        return redirect('project_detail', pk=project.pk)

    return render(request, 'projects/edit.html', {'form': form, 'project': project})
# projects/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .forms import ProjectForm
from .models import Project
from .services import can_activate, set_project_state


@login_required
def project_create(request):
    form = ProjectForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        project = form.save(commit=False)
        project.owner = request.user
        project.state = Project.State.INACTIVE
        project.save()

        wants_active = form.cleaned_data.get('activate')
        activation_error = None

        if wants_active:
            ok, reason = can_activate(project)
            if ok:
                # set_project_state handles the actual transition and task locking.
                set_project_state(project)
                project.refresh_from_db()
                if project.state != Project.State.ACTIVE:
                    # No visible tasks yet — can't be active.
                    activation_error = 'no_tasks'
            else:
                activation_error = reason

        if activation_error:
            return render(request, 'projects/create.html', {
                'form': form,
                'project': project,
                'activation_error': activation_error,
            })

        return redirect('project_detail', pk=project.pk)

    return render(request, 'projects/create.html', {'form': form})


@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    tasks   = project.tasks.filter(is_deleted=False).order_by('created_at')

    # Per-task health summary for the owner dashboard.
    # hidden=True may mean system-flagged (health failure) or owner-hidden.
    return render(request, 'projects/detail.html', {
        'project': project,
        'tasks':   tasks,
    })


@login_required
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    form    = ProjectForm(request.POST or None, instance=project,
                          initial={'activate': project.state == Project.State.ACTIVE})

    if request.method == 'POST' and form.is_valid():
        form.save()

        wants_active     = form.cleaned_data.get('activate')
        activation_error = None

        if wants_active:
            ok, reason = can_activate(project)
            if ok:
                set_project_state(project)
                project.refresh_from_db()
                if project.state != Project.State.ACTIVE:
                    activation_error = 'no_tasks'
            else:
                activation_error = reason
        else:
            # Owner explicitly unchecked — force inactive.
            if project.state == Project.State.ACTIVE:
                project.state = Project.State.INACTIVE
                project.save(update_fields=['state'])

        if activation_error:
            return render(request, 'projects/edit.html', {
                'form': form,
                'project': project,
                'activation_error': activation_error,
            })

        return redirect('project_detail', pk=project.pk)

    return render(request, 'projects/edit.html', {
        'form': form,
        'project': project,
    })