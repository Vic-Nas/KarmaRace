"""Task checking and completion views."""
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from tasks.check_feedback import msg
from tasks.models import Task, TaskCompletion, ReciprocityObligation

from .filtering import DEFAULT_COMPLETION, DEFAULT_ARCHIVE, SESSION_FEED_PIN_KEY, normalize_task_types


def redirect_to_feed_with_filters(request, extra_params=None):
    """Redirect back to feed with current filter settings."""
    from django.urls import reverse
    from django.utils.http import urlencode

    completion     = (request.POST.get('completion') or DEFAULT_COMPLETION).strip() or DEFAULT_COMPLETION
    archive        = (request.POST.get('archive') or DEFAULT_ARCHIVE).strip() or DEFAULT_ARCHIVE
    selected_types = normalize_task_types(request.POST.getlist('task_types'))

    from .filtering import save_filter_preferences
    save_filter_preferences(request.user, completion, archive, selected_types)
    params = {k: v for k, v in (extra_params or {}).items() if v not in (None, '', [])}
    url = reverse('feed')
    return redirect(f'{url}?{urlencode(params, doseq=True)}') if params else redirect(url)


def precheck_linked_account(user, task):
    """Check if user has required linked account for task type."""
    if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
        if not user.linked_accounts.filter(platform='github').exists():
            return msg('GITHUB_LINK_REQUIRED')
    return None


def _compute_completion_reward(user, task):
    """
    Snapshot the karma reward at check time.

    If this completion settles an open obligation toward the task owner,
    reward the tester as if they had completed the top free-feed task instead
    (opportunity cost compensation). The owner still pays only their normal reward.
    If no obligation applies, return the normal computed reward.
    """
    from karma.services import get_balance
    from setup.platform_rules import karma_reward_for_task
    from .queries import feed_queryset

    normal_reward = karma_reward_for_task(get_balance(task.owner), task.type)

    has_obligation = ReciprocityObligation.objects.filter(
        debtor=user,
        creditor=task.owner,
        task_type=task.type,
        state=ReciprocityObligation.State.OPEN,
    ).exists()

    if not has_obligation:
        return normal_reward

    # Find top task user would have gotten without obligations
    top_free_task = feed_queryset(user, completion='not_completed', archive='not_archived').first()
    if top_free_task is None:
        return normal_reward

    opportunity_reward = karma_reward_for_task(top_free_task.owner_balance, top_free_task.type)
    return max(normal_reward, opportunity_reward)


@require_POST
def done(request, task_id):
    """Archive a task."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    from .queries import active_lock_obligations, open_obligations

    obligations = active_lock_obligations(request.user, open_obligations(request.user))
    if obligations:
        messages.error(request, msg('ARCHIVE_DISABLED_OBLIGATIONS'))
        return redirect_to_feed_with_filters(request)
    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id != request.user.id:
        task.archived_by.add(request.user)
        if request.session.get(SESSION_FEED_PIN_KEY) == task.id:
            request.session.pop(SESSION_FEED_PIN_KEY, None)
    return redirect_to_feed_with_filters(request)


@require_POST
def check(request, task_id):
    """Check a task (submit completion attempt)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def respond(state, detail='', extra_params=None):
        if is_ajax:
            payload = {'state': state}
            if detail:       payload['detail'] = detail
            if extra_params: payload.update(extra_params)
            return JsonResponse(payload)
        if state == TaskCompletion.State.CONFIRMED:
            messages.success(request, detail or msg('CHECK_CONFIRMED'))
            return redirect_to_feed_with_filters(request)
        if state == TaskCompletion.State.FAILED:
            messages.error(request, detail or msg('CHECK_FAILED_GENERIC'))
            return redirect_to_feed_with_filters(request)
        if state == TaskCompletion.State.PENDING:
            messages.info(request, detail or msg('CHECK_STARTED'))
            return redirect_to_feed_with_filters(request, extra_params={'checking_task': str(task.pk)})
        return redirect_to_feed_with_filters(request)

    if not request.user.is_authenticated:
        if is_ajax:
            return JsonResponse({'state': 'UNAUTHENTICATED', 'detail': 'Sign in required.'}, status=401)
        return redirect('account_login')

    from feed.tasks import process_task_check
    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id == request.user.id:
        return respond(TaskCompletion.State.FAILED, 'You cannot check your own task.')

    precheck_error = precheck_linked_account(request.user, task)
    if precheck_error:
        return respond(TaskCompletion.State.FAILED, precheck_error)

    google_email = ''
    if task.type == Task.Type.WEBHOOK:
        google_email = (request.POST.get('google_email') or '').strip()
        if not google_email:
            return respond(TaskCompletion.State.FAILED, 'Select a verified email before checking a webhook task.')
        diff_raw = (request.POST.get('difficulty') or '').strip()
        if not diff_raw or not diff_raw.isdigit() or not (1 <= int(diff_raw) <= 5):
            return respond(TaskCompletion.State.FAILED, 'Rate the task difficulty (1–5) before checking.')
        from accounts.models import UserPreference
        UserPreference.objects.update_or_create(
            user=request.user, key=f'task_diff_pick_{task.pk}', defaults={'value': diff_raw})

    reward = _compute_completion_reward(request.user, task)

    completion, created = TaskCompletion.objects.get_or_create(
        task=task, tester=request.user,
        defaults={'state': TaskCompletion.State.PENDING, 'reward': reward},
    )

    if completion.state == TaskCompletion.State.CONFIRMED:
        from karma.services import get_balance
        return respond(TaskCompletion.State.CONFIRMED, msg('ALREADY_CONFIRMED'),
                       extra_params={'karma_delta': 0, 'karma_balance': get_balance(request.user)})

    if completion.state == TaskCompletion.State.PENDING and not created:
        if completion.created_at <= timezone.now() - timedelta(seconds=45):
            completion.state = TaskCompletion.State.FAILED
            completion.save(update_fields=['state'])
        else:
            return respond(TaskCompletion.State.PENDING, msg('CHECK_IN_PROGRESS'))

    if not created:
        completion.state         = TaskCompletion.State.PENDING
        completion.result_detail = ''
        completion.reward        = reward
        completion.created_at    = timezone.now()
        completion.save(update_fields=['state', 'result_detail', 'reward', 'created_at'])

    process_task_check.defer(task_id=task.pk, tester_id=request.user.pk, google_email=google_email)

    return respond(TaskCompletion.State.PENDING, msg('CHECK_STARTED'))


def check_status(request, task_id):
    """Poll for task check status."""
    if not request.user.is_authenticated:
        return JsonResponse({'state': 'UNAUTHENTICATED'}, status=401)
    completion = TaskCompletion.objects.filter(task_id=task_id, tester=request.user).first()
    if completion is None:
        return JsonResponse({'state': 'NOT_STARTED'})
    if (completion.state == TaskCompletion.State.PENDING
            and completion.created_at <= timezone.now() - timedelta(seconds=45)):
        completion.state         = TaskCompletion.State.FAILED
        completion.result_detail = msg('CHECK_TIMEOUT_WORKER_HINT') if settings.DEBUG else msg('CHECK_TIMEOUT')
        completion.save(update_fields=['state', 'result_detail'])
        return JsonResponse({'state': TaskCompletion.State.FAILED, 'detail': completion.result_detail})
    if completion.state == TaskCompletion.State.FAILED:
        return JsonResponse({'state': completion.state,
                             'result_code': completion.result_code or '',
                             'detail': completion.result_detail or msg('CHECK_FAILED_GENERIC')})
    if completion.state == TaskCompletion.State.CONFIRMED:
        from karma.services import get_balance
        return JsonResponse({'state': completion.state, 'detail': msg('CHECK_CONFIRMED'),
                             'karma_delta': completion.reward,
                             'karma_balance': get_balance(request.user)})
    return JsonResponse({'state': completion.state})


@require_POST
def switch(request):
    """
    Cycle to the next valid obligation task for the current creditor/type pair.
    Session key: feed_obligation_switch_{creditor_id}_{task_type}
    """
    if not request.user.is_authenticated:
        return redirect('account_login')

    from .queries import open_obligations, active_lock_obligations, get_obligation_tasks
    from .filtering import SESSION_FEED_PIN_KEY

    obligations = active_lock_obligations(request.user, open_obligations(request.user))
    if not obligations:
        return redirect_to_feed_with_filters(request)

    # Use the first (oldest) active obligation — same as feed_view priority
    ob = obligations[0]
    tasks = get_obligation_tasks(request.user, ob)
    if not tasks:
        return redirect_to_feed_with_filters(request)

    session_key = f'feed_obligation_switch_{ob.creditor_id}_{ob.task_type}'
    current_index = request.session.get(session_key, 0)
    next_index = (current_index + 1) % len(tasks)
    request.session[session_key] = next_index

    # Pin the selected task
    next_task = tasks[next_index]
    request.session[SESSION_FEED_PIN_KEY] = next_task.pk

    return redirect_to_feed_with_filters(request)
