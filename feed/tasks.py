# feed/tasks.py
import logging

from procrastinate.contrib.django import app
from django.db import transaction

from karma.models import KarmaTransaction
from karma.services import credit_karma, debit_karma, get_balance
from setup.platform_rules import karma_reward_for_task
from tasks.check_feedback import msg
from tasks.models import Task, TaskCompletion
from tasks.services import verify_task_with_details

logger = logging.getLogger(__name__)


@app.task
def process_task_check(task_id: int, tester_id: int, google_email: str = ''):
    """Background verification for a queued task check."""
    try:
        task = Task.objects.select_related('owner').get(pk=task_id, is_deleted=False, hidden=False)
    except Task.DoesNotExist:
        logger.error('process_task_check: task %s not found/visible', task_id)
        return

    completion, _ = TaskCompletion.objects.get_or_create(
        task=task,
        tester_id=tester_id,
        defaults={'state': TaskCompletion.State.PENDING, 'result_detail': ''},
    )

    if completion.state == TaskCompletion.State.CONFIRMED:
        return

    with transaction.atomic():
        task.tried_count += 1

        ok, detail, result_code = verify_task_with_details(task, completion.tester, google_email=google_email)
        if ok:
            if completion.state != TaskCompletion.State.CONFIRMED:
                completion.state = TaskCompletion.State.CONFIRMED
                completion.result_detail = msg('CHECK_CONFIRMED')
                completion.save(update_fields=['state', 'result_detail'])

                tester_reward = completion.reward
                owner_cost = karma_reward_for_task(get_balance(task.owner), task.type)
                if tester_reward > 0:
                    credit_karma(
                        user=completion.tester,
                        delta=tester_reward,
                        reason=KarmaTransaction.Reason.TASK_EARNED,
                        related_object_id=task.pk,
                    )
                if owner_cost > 0:
                    debit_karma(
                        user=task.owner,
                        delta=owner_cost,
                        reason=KarmaTransaction.Reason.TASK_COST,
                        related_object_id=task.pk,
                    )

                if task.type == Task.Type.WEBHOOK:
                    from accounts.models import UserPreference
                    pref = UserPreference.objects.filter(user=completion.tester, key=f'task_diff_pick_{task.pk}').first()
                    if pref and pref.value.isdigit():
                        completed_difficulty = max(1, min(5, int(pref.value)))
                        task.difficulty_sum += completed_difficulty
                        task.difficulty_count += 1
                        pref.delete()

                task.succeed_count += 1
                logger.info('process_task_check: task %s confirmed for tester %s', task.pk, tester_id)
        else:
            completion.state = TaskCompletion.State.FAILED
            completion.result_detail = detail or msg('CHECK_FAILED_GENERIC')
            completion.result_code = result_code or ''
            completion.save(update_fields=['state', 'result_detail', 'result_code'])
            logger.info('process_task_check: task %s failed for tester %s: %s', task.pk, tester_id, detail)

        task.save(update_fields=['tried_count', 'succeed_count', 'difficulty_sum', 'difficulty_count'])
