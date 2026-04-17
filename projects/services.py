# projects/services.py
from projects.models import Project


def can_activate(project) -> tuple[bool, str]:
    """
    Returns (True, '') if project can go ACTIVE.
    Returns (False, reason) if blocked.

    Free users may not activate a project that has an unhidden webhook task —
    they must either hide it or upgrade to Pro.
    """
    if not project.owner.is_pro:
        has_unhidden_webhook = project.tasks.filter(
            type='WEBHOOK',
            is_deleted=False,
            hidden=False,
        ).exists()
        if has_unhidden_webhook:
            return False, 'hide_or_upgrade'
    return True, ''


def set_project_state(project):
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

    if has_tasks:
        ok, reason = can_activate(project)
        if not ok:
            # Activation blocked (e.g. unhidden webhook task on free account).
            if project.state != Project.State.INACTIVE:
                project.state            = Project.State.INACTIVE
                project.went_inactive_at = timezone.now()
                project.save(update_fields=['state', 'went_inactive_at'])
            return

        if project.state != Project.State.ACTIVE:
            project.state            = Project.State.ACTIVE
            project.went_inactive_at = None
            project.save(update_fields=['state', 'went_inactive_at'])
            lock_tasks(project)
    else:
        if project.state != Project.State.INACTIVE:
            project.state            = Project.State.INACTIVE
            project.went_inactive_at = timezone.now()
            project.save(update_fields=['state', 'went_inactive_at'])