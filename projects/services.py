# projects/services.py
from projects.models import Project


def has_testable_projects(user) -> bool:
    """
    Returns True if there are active projects the user can still test.
    Excludes projects owned by the user and projects they have archived.
    Used by karma/services.py to skip debit when the feed is exhausted.
    """
    qs = Project.objects.filter(state=Project.State.ACTIVE)

    if user.is_authenticated:
        qs = qs.exclude(owner=user)
        qs = qs.exclude(archived_by=user)

    return qs.exists()


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
    Call after any karma change, task addition, task removal, or task hide/unhide.

    - Only non-deleted, non-hidden tasks count toward "has tasks".
    - Transitions to ACTIVE are gated by can_activate().
    - Transitions to ACTIVE call lock_tasks() to prevent further task edits.
    """
    from django.utils import timezone
    from karma.services import get_balance
    from tasks.services import lock_tasks

    has_tasks = project.tasks.filter(is_deleted=False, hidden=False).exists()
    balance   = get_balance(project.owner)

    if has_tasks and balance > 0:
        ok, reason = can_activate(project)
        if not ok:
            # Cannot activate; ensure project is INACTIVE.
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