# billing/views.py
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from djstripe.models import Customer, Subscription

def _stripe_client():
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def _absolute_url(request, path):
    return request.build_absolute_uri(path)


def _ensure_customer(request):
    stripe = _stripe_client()

    customer = Customer.objects.filter(subscriber=request.user).first()
    if customer and customer.id:
        return customer.id

    created = stripe.Customer.create(
        email=request.user.email or None,
        name=request.user.username,
        metadata={'user_id': str(request.user.pk)},
    )
    Customer.sync_from_stripe_data(created)
    return created.id


@login_required
def billing_plan(request):
    checkout_state = request.GET.get('checkout')
    if checkout_state == 'success':
        messages.success(request, 'Stripe checkout completed. Subscription status will update shortly.')
    elif checkout_state == 'cancel':
        messages.info(request, 'Checkout was canceled.')

    subscription = (
        Subscription.objects
        .filter(customer__subscriber=request.user)
        .order_by('-created')
        .first()
    )

    return render(request, 'billing/plan.html', {
        'subscription_status': subscription.status if subscription else '',
        'stripe_price_id': settings.STRIPE_PRICE_ID,
    })


@login_required
@require_POST
def start_checkout(request):
    stripe = _stripe_client()
    customer_id = _ensure_customer(request)

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
    customer_id = _ensure_customer(request)

    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=_absolute_url(request, reverse('billing_plan')),
    )
    return redirect(portal.url)
