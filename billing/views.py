# billing/views.py
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from billing.models import BillingProfile


def _stripe_client():
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def _absolute_url(request, path):
    return request.build_absolute_uri(path)


def _billing_profile(user):
    profile, _ = BillingProfile.objects.get_or_create(user=user)
    return profile


def _ensure_customer(request, profile):
    stripe = _stripe_client()

    if profile.stripe_customer_id:
        return profile.stripe_customer_id

    customer = stripe.Customer.create(
        email=request.user.email or None,
        name=request.user.username,
        metadata={'user_id': str(request.user.pk)},
    )
    profile.stripe_customer_id = customer.id
    profile.save(update_fields=['stripe_customer_id'])
    return customer.id


def _set_user_pro(user, is_pro):
    if user.is_pro != is_pro:
        user.is_pro = is_pro
        user.save(update_fields=['is_pro'])


@login_required
def billing_plan(request):
    profile = _billing_profile(request.user)

    checkout_state = request.GET.get('checkout')
    if checkout_state == 'success':
        messages.success(request, 'Stripe checkout completed. Subscription status will update shortly.')
    elif checkout_state == 'cancel':
        messages.info(request, 'Checkout was canceled.')

    return render(request, 'billing/plan.html', {
        'profile': profile,
        'stripe_price_id': settings.STRIPE_PRICE_ID,
    })


@login_required
@require_POST
def start_checkout(request):
    stripe = _stripe_client()
    profile = _billing_profile(request.user)
    customer_id = _ensure_customer(request, profile)

    success_url = _absolute_url(request, reverse('billing_plan') + '?checkout=success')
    cancel_url = _absolute_url(request, reverse('billing_plan') + '?checkout=cancel')

    session = stripe.checkout.Session.create(
        mode='subscription',
        customer=customer_id,
        line_items=[{'price': settings.STRIPE_PRICE_ID, 'quantity': 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={'user_id': str(request.user.pk)},
    )
    return redirect(session.url)


@login_required
@require_POST
def billing_portal(request):
    stripe = _stripe_client()
    profile = _billing_profile(request.user)
    customer_id = _ensure_customer(request, profile)

    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=_absolute_url(request, reverse('billing_plan')),
    )
    return redirect(portal.url)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    stripe = _stripe_client()

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return HttpResponseBadRequest('Invalid payload')
    except stripe.error.SignatureVerificationError:
        return HttpResponseBadRequest('Invalid signature')

    event_type = event.get('type', '')
    data = event.get('data', {}).get('object', {})

    if event_type == 'checkout.session.completed':
        user_id = (data.get('metadata') or {}).get('user_id')
        customer_id = data.get('customer') or ''
        subscription_id = data.get('subscription') or ''

        if user_id:
            try:
                user = get_user_model().objects.get(pk=user_id)
            except Exception:
                user = None
            if user:
                profile = _billing_profile(user)
                profile.stripe_customer_id = customer_id or profile.stripe_customer_id
                profile.stripe_subscription_id = subscription_id or profile.stripe_subscription_id
                profile.subscription_status = 'active'
                profile.save(update_fields=['stripe_customer_id', 'stripe_subscription_id', 'subscription_status'])
                _set_user_pro(user, True)

    elif event_type in ('customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted'):
        customer_id = data.get('customer') or ''
        subscription_id = data.get('id') or ''
        status = data.get('status') or ''
        period_end_ts = data.get('current_period_end')

        if customer_id:
            profile = BillingProfile.objects.filter(stripe_customer_id=customer_id).select_related('user').first()
            if profile:
                profile.stripe_subscription_id = subscription_id
                profile.subscription_status = status
                profile.current_period_end = (
                    datetime.fromtimestamp(period_end_ts, tz=dt_timezone.utc)
                    if period_end_ts else None
                )
                profile.save(update_fields=['stripe_subscription_id', 'subscription_status', 'current_period_end'])
                _set_user_pro(profile.user, status in ('active', 'trialing'))

    return JsonResponse({'received': True})
