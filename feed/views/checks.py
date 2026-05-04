# feed/views/checks.py
"""Task checking and completion views."""
from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from karma.services import get_balance
from setup.platform_rules import karma_reward_for_task
from tasks.check_feedback import msg
from tasks.models import Task, TaskCompletion
from .filtering import DEFAULT_COMPLETION, DEFAULT_ARCHIVE, SESSION_FEED_PIN_KEY, normalize_task_types
from feed.forms import WebhookCheckForm

CHECK_TIMEOUT_SECONDS = 45


def redirect_to_feed_with_filters(request, extra_params=None):
    """Redirect back to feed with current filter settings."""
    from django.urls import reverse
    from django.utils.http import urlencode
    from .filtering import save_filter_preferences

    completion     = (request.POST.get('completion') or DEFAULT_COMPLETION).strip() or DEFAULT_COMPLETION
    archive        = (request.POST.get('archive') or DEFAULT_ARCHIVE).strip() or DEFAULT_ARCHIVE
    selected_types = normalize_task_types(request.POST.getlist('task_types'))
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


def _is_timed_out(completion):
    return completion.created_at <= timezone.now() - timedelta(seconds=CHECK_TIMEOUT_SECONDS)


@require_POST
def done(request, task_id):
    """Archive a task."""
    if not request.user.is_authenticated:
        return redirect('account_login')
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
        if state == TaskCompletion.State.PENDING:
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
        form = WebhookCheckForm(request.POST)
        if not form.is_valid():
            return respond(TaskCompletion.State.FAILED, 'Select a verified email and rate difficulty (1–5).')
        google_email = form.cleaned_data['google_email']
        from accounts.models import UserPreference
        UserPreference.objects.update_or_create(
            user=request.user, key=f'task_diff_pick_{task.pk}',
            defaults={'value': str(form.cleaned_data["difficulty"])}
        )

    reward = karma_reward_for_task(get_balance(task.owner), task.type)

    completion, created = TaskCompletion.objects.get_or_create(
        task=task, tester=request.user,
        defaults={'state': TaskCompletion.State.PENDING, 'reward': reward},
    )

    if completion.state == TaskCompletion.State.CONFIRMED:
        return respond(TaskCompletion.State.CONFIRMED, msg('ALREADY_CONFIRMED'),
                       extra_params={'karma_delta': 0, 'karma_balance': get_balance(request.user)})

    if completion.state == TaskCompletion.State.PENDING and not created:
        if _is_timed_out(completion):
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
    if completion.state == TaskCompletion.State.PENDING and _is_timed_out(completion):
        completion.state         = TaskCompletion.State.FAILED
        completion.result_detail = msg('CHECK_TIMEOUT_WORKER_HINT') if settings.DEBUG else msg('CHECK_TIMEOUT')
        completion.save(update_fields=['state', 'result_detail'])
        return JsonResponse({'state': TaskCompletion.State.FAILED, 'detail': completion.result_detail})
    if completion.state == TaskCompletion.State.FAILED:
        return JsonResponse({'state': completion.state,
                             'result_code': completion.result_code or '',
                             'detail': completion.result_detail or msg('CHECK_FAILED_GENERIC')})
    if completion.state == TaskCompletion.State.CONFIRMED:
        return JsonResponse({'state': completion.state, 'detail': msg('CHECK_CONFIRMED'),
                             'karma_delta': completion.reward,
                             'karma_balance': get_balance(request.user)})
    return JsonResponse({'state': completion.state})
