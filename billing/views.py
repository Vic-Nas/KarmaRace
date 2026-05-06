# billing/views.py
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from djstripe.models import Subscription


@login_required
def billing_plan(request):
    checkout_state = request.GET.get('checkout')
    if checkout_state == 'success':
        messages.success(request, 'Subscription confirmed. Pro access will activate shortly.')
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
        'stripe_buy_button_id': settings.STRIPE_BUY_BUTTON_ID,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
    })


@login_required
def billing_portal(request):
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    from djstripe.models import Customer
    customer = Customer.objects.filter(subscriber=request.user).first()
    if not customer:
        messages.error(request, 'No billing account found.')
        return redirect(reverse('billing_plan'))
    portal = stripe.billing_portal.Session.create(
        customer=customer.id,
        return_url=request.build_absolute_uri(reverse('billing_plan')),
    )
    return redirect(portal.url)
