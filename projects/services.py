# projects/services.py
from projects.models import Project


def can_activate(project) -> tuple[bool, str]:
    """
    Returns (True, '') if project can go ACTIVE.
    Returns (False, reason) if blocked.

    Free users may not activate a project that has an unhidden webhook task —
    they must either hide it or upgrade to Pro.
    """
    visible_tasks = project.tasks.filter(is_deleted=False, hidden=False)
    if not visible_tasks.exists():
        return False, 'no_tasks'

    if not project.owner.is_pro:
        has_unhidden_webhook = project.tasks.filter(
            type='WEBHOOK',
            is_deleted=False,
            hidden=False,
        ).exists()
        if has_unhidden_webhook:
            return False, 'hide_or_upgrade'

    from tasks.services import is_task_configuration_valid

    for task in visible_tasks:
        if not is_task_configuration_valid(task):
            return False, 'invalid_tasks'

    return True, ''


def set_project_state(project, allow_activate=False):
    """
    Recomputes and applies the correct state for a project.
    Call after any task addition, task removal, or task hide/unhide.

    - ACTIVE requires: at least one visible task (is_deleted=False, hidden=False),
      and no unhidden webhook tasks when owner is not Pro.
    - Karma balance does NOT gate ACTIVE. Zero-karma projects stay ACTIVE and
      simply rank at the bottom of the feed.
    - went_inactive_at is set only when transitioning to INACTIVE.
    """
    from django.utils import timezone
    from tasks.services import lock_tasks

    has_tasks = project.tasks.filter(is_deleted=False, hidden=False).exists()

    ok, _reason = can_activate(project)

    should_be_active = allow_activate and has_tasks and ok
    should_be_inactive = (not has_tasks) or (not ok)

    if should_be_active and project.state != Project.State.ACTIVE:
        project.state = Project.State.ACTIVE
        project.went_inactive_at = None
        project.save(update_fields=['state', 'went_inactive_at'])
        return

    if should_be_inactive and project.state != Project.State.INACTIVE:
        project.state = Project.State.INACTIVE
        project.went_inactive_at = timezone.now()
        project.save(update_fields=['state', 'went_inactive_at'])
        lock_tasks(project)