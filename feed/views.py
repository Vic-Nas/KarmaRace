# feed/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.db.models import Count, Q

from projects.models import Project
from tasks.models import TaskCompletion


def _feed_queryset(user):
    """
    Active projects ranked by owner karma balance (descending).
    Excludes projects owned by the viewing user.
    Excludes projects the viewing user has already archived (Done'd).
    """
    from django.db.models import Sum

    qs = Project.objects.filter(state=Project.State.ACTIVE)

    if user.is_authenticated:
        qs = qs.exclude(owner=user)
        qs = qs.exclude(archived_by=user)

    qs = qs.annotate(
        owner_balance=Sum('owner__karma_transactions__delta')
    ).order_by('-owner_balance', 'created_at')

    return qs


def _get_feed_project(user):
    """
    Picks the first valid feed candidate after running lazy health checks.

    For each candidate:
    1. Run run_health_check() on every non-deleted, non-hidden task.
    2. Call set_project_state() to pick up any hidden tasks → possible INACTIVE.
    3. If the project is still ACTIVE, return it.
    4. Otherwise advance to the next candidate.

    Returns None when the feed is exhausted.
    """
    from tasks.services import run_health_check
    from projects.services import set_project_state

    qs = _feed_queryset(user)

    for project in qs.iterator():
        live_tasks = list(project.tasks.filter(is_deleted=False, hidden=False))

        for task in live_tasks:
            run_health_check(task)

        # Refresh state — some tasks may now be hidden.
        project.refresh_from_db()
        set_project_state(project)
        project.refresh_from_db()

        if project.state == Project.State.ACTIVE:
            return project

    return None


def feed(request):
    project = _get_feed_project(request.user)

    completed_task_ids = set()
    has_completion = False

    if project and request.user.is_authenticated:
        completed_task_ids = set(
            TaskCompletion.objects.filter(
                tester=request.user,
                task__project=project,
                state=TaskCompletion.State.CONFIRMED,
            ).values_list('task_id', flat=True)
        )
        has_completion = bool(completed_task_ids)

    # Show only live tasks to the tester.
    tasks = (
        project.tasks.filter(is_deleted=False, hidden=False)
        if project else []
    )

    return render(request, 'feed/index.html', {
        'project':           project,
        'tasks':             tasks,
        'completed_task_ids': completed_task_ids,
        'has_completion':    has_completion,
        'feed_empty':        project is None,
    })


@require_POST
def done(request, project_id):
    """
    Auto-archive the current project for this user and advance the feed.
    """
    if not request.user.is_authenticated:
        return redirect('account_login')

    project = get_object_or_404(Project, pk=project_id, state=Project.State.ACTIVE)
    project.archived_by.add(request.user)

    return redirect('feed')