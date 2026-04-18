import logging

import procrastinate
from django.db import transaction

from karma.models import KarmaTransaction
from karma.services import credit_karma, debit_karma
from setup.platform_rules import KARMA_REWARDS_BY_TASK_TYPE
from tasks.models import Task, TaskCompletion
from tasks.services import verify_task_with_details, settle_or_create_obligation

logger = logging.getLogger(__name__)

app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector())


@app.task
def process_task_check(task_id: int, tester_id: int):
    """Background verification for a queued task check."""
    try:
        task = Task.objects.select_related('owner').get(pk=task_id, is_deleted=False, hidden=False)
    except Task.DoesNotExist:
        logger.error('process_task_check: task %s not found/visible', task_id)
        return

    completion, _ = TaskCompletion.objects.get_or_create(
        task=task,
        tester_id=tester_id,
        defaults={'state': TaskCompletion.State.PENDING},
    )

    if completion.state == TaskCompletion.State.CONFIRMED:
        return

    with transaction.atomic():
        task.tried_count += 1

        ok, detail = verify_task_with_details(task, completion.tester)
        if ok:
            if completion.state != TaskCompletion.State.CONFIRMED:
                completion.state = TaskCompletion.State.CONFIRMED
                completion.save(update_fields=['state'])

                reward = int(KARMA_REWARDS_BY_TASK_TYPE.get(task.type, 0) or 0)
                if reward > 0:
                    credit_karma(
                        user=completion.tester,
                        delta=reward,
                        reason=KarmaTransaction.Reason.TASK_EARNED,
                        related_object_id=task.pk,
                    )
                    debit_karma(
                        user=task.owner,
                        delta=reward,
                        reason=KarmaTransaction.Reason.TASK_COST,
                        related_object_id=task.pk,
                    )

                settle_or_create_obligation(
                    actor=completion.tester,
                    counterparty=task.owner,
                    task_type=task.type,
                    completed_task=task,
                )

                task.succeed_count += 1
                logger.info('process_task_check: task %s confirmed for tester %s', task.pk, tester_id)
        else:
            completion.state = TaskCompletion.State.FAILED
            completion.save(update_fields=['state'])
            logger.info(
                'process_task_check: task %s failed for tester %s: %s',
                task.pk,
                tester_id,
                detail,
            )

        task.save(update_fields=['tried_count', 'succeed_count'])
