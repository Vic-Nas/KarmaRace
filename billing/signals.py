# billing/signals.py
import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from djstripe.models import Subscription
from djstripe.signals import WEBHOOK_SIGNALS

logger = logging.getLogger(__name__)

User = get_user_model()


def _sync_user_pro(user):
    if user is None:
        return
    is_active = Subscription.objects.filter(
        customer__subscriber=user,
        status__in=('active', 'trialing'),
    ).exists()
    if user.is_pro != is_active:
        user.is_pro = is_active
        user.save(update_fields=['is_pro'])


@receiver(post_save, sender=Subscription)
def subscription_saved(sender, instance, **kwargs):
    customer = instance.customer
    user = customer.subscriber if customer else None
    _sync_user_pro(user)


@receiver(post_delete, sender=Subscription)
def subscription_deleted(sender, instance, **kwargs):
    customer = instance.customer
    user = customer.subscriber if customer else None
    _sync_user_pro(user)


@receiver(WEBHOOK_SIGNALS['checkout.session.completed'])
def checkout_completed(sender, event, **kwargs):
    """
    Link the Stripe customer to the Django user via client_reference_id.
    Fired when the Buy Button checkout completes — before the subscription
    webhook, so the customer↔user link exists by the time _sync_user_pro runs.
    """
    session = event.data['object']
    user_pk = session.get('client_reference_id')
    customer_id = session.get('customer')

    if not user_pk or not customer_id:
        logger.warning('checkout.session.completed missing user_pk or customer_id')
        return

    try:
        user = User.objects.get(pk=user_pk)
    except User.DoesNotExist:
        logger.warning('checkout.session.completed: no user with pk=%s', user_pk)
        return

    from djstripe.models import Customer
    customer, _ = Customer.get_or_retrieve_stripe_object(customer_id)
    customer.subscriber = user
    customer.save(update_fields=['subscriber'])
    logger.info('linked Stripe customer %s to user %s', customer_id, user_pk)
