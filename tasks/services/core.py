"""Core task operations: verification, obligations, rewards, deletion."""
import logging
from django.utils import timezone
from django.db import transaction

from tasks.models import Task, TaskCompletion, ReciprocityObligation
from tasks.check_feedback import msg
from setup.platform_rules import karma_reward_for_task

logger = logging.getLogger(__name__)


def verify_task_with_details(task, tester, google_email=''):
    """Verify a task completion. Dispatches by task type."""
    from .verify import verify_github_with_details, verify_webhook_with_details
    
    dispatch = {
        Task.Type.GITHUB_STAR: verify_github_with_details,
        Task.Type.GITHUB_FORK: verify_github_with_details,
        Task.Type.WEBHOOK:     verify_webhook_with_details,
    }
    verifier = dispatch.get(task.type)
    if verifier is None:
        logger.error('verify_task: unknown task type %s', task.type)
        return False, msg('UNKNOWN_TASK_TYPE')
    if task.type == Task.Type.WEBHOOK:
        return verifier(task, tester, google_email=google_email)
    return verifier(task, tester)


def soft_delete_task(task):
    """Soft-delete a task and fail any pending completions."""
    task.is_deleted = True
    task.save(update_fields=['is_deleted'])
    TaskCompletion.objects.filter(
        task=task,
        state=TaskCompletion.State.PENDING,
    ).update(state=TaskCompletion.State.FAILED, result_detail=msg('ARCHIVED_DURING_CHECK'))


@transaction.atomic
def settle_or_create_obligation(actor, counterparty, task_type, completed_task):
    """Settle existing debt first; otherwise create reverse obligation."""
    if actor.pk == counterparty.pk:
        return None

    debt = ReciprocityObligation.objects.select_for_update().filter(
        debtor=actor,
        creditor=counterparty,
        task_type=task_type,
        state=ReciprocityObligation.State.OPEN,
    ).order_by('created_at').first()

    if debt:
        debt.state = ReciprocityObligation.State.FULFILLED
        debt.fulfilled_by_task = completed_task
        debt.fulfilled_at = timezone.now()
        debt.save(update_fields=['state', 'fulfilled_by_task', 'fulfilled_at'])
        return 'settled'

    ReciprocityObligation.objects.create(
        debtor=counterparty,
        creditor=actor,
        task_type=task_type,
        state=ReciprocityObligation.State.OPEN,
        source_task=completed_task,
    )
    return 'created'


def assign_task_karma_reward(task):
    """Compute and persist karma_reward based on owner's current balance."""
    from karma.services import get_balance
    owner_karma = get_balance(task.owner)
    task.karma_reward = karma_reward_for_task(owner_karma, task.type)
    task.save(update_fields=['karma_reward'])


def on_task_unhidden(task):
    """When task is unhidden, unarchive it for users who completed it."""
    completed_user_ids = TaskCompletion.objects.filter(
        task=task, state=TaskCompletion.State.CONFIRMED,
    ).values_list('tester_id', flat=True)
    users_to_unarchive = task.archived_by.exclude(id__in=completed_user_ids)
    if users_to_unarchive:
        task.archived_by.remove(*users_to_unarchive)
