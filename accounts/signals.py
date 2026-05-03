# accounts/signals.py
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

import requests

from accounts import discord as discord_api
from accounts.models import LinkedAccount, User, VerifiedEmail


def _seed_verified_email_from_social(social_account):
    if social_account.provider != 'google':
        return
    email = (social_account.extra_data.get('email') or '').strip().lower()
    if email:
        VerifiedEmail.objects.get_or_create(user=social_account.user, email=email)


try:
    from allauth.socialaccount.signals import social_account_added, social_account_updated

    @receiver(social_account_added)
    def _on_social_account_added(sender, request, sociallogin, **kwargs):
        try:
            _seed_verified_email_from_social(sociallogin.account)
        except Exception:
            pass

    @receiver(social_account_updated)
    def _on_social_account_updated(sender, request, sociallogin, **kwargs):
        try:
            _seed_verified_email_from_social(sociallogin.account)
        except Exception:
            pass

except ImportError:
    pass


@receiver(pre_save, sender=User)
def _capture_old_username(sender, instance: User, **kwargs):
    if not instance.pk:
        instance._old_username = None
        return
    old = sender.objects.filter(pk=instance.pk).values_list('username', flat=True).first()
    instance._old_username = old


@receiver(post_save, sender=User)
def _sync_discord_nickname_on_username_change(sender, instance: User, created: bool, **kwargs):
    if created:
        return

    old_username = getattr(instance, '_old_username', None)
    if old_username == instance.username:
        return

    linked = LinkedAccount.objects.filter(user=instance, platform=LinkedAccount.DISCORD).first()
    if not linked:
        return

    try:
        if discord_api.is_member(linked.platform_id):
            discord_api.sync_nickname(linked.platform_id, instance.username)
            discord_api.ensure_role(linked.platform_id)
        else:
            linked.delete()
    except requests.RequestException:
        # Best-effort sync; user can relink from the Discord entrypoint if needed.
        return
