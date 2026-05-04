from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from djstripe.models import Subscription


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
