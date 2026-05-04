# accounts/signals.py
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

import requests

from accounts import discord as discord_api
from accounts.models import LinkedAccount, User, VerifiedEmail

# 1–50: notify on every signup.
# Beyond 50: only notify at these milestones.
_MILESTONES = {100, 250, 500, 1_000, 2_000, 5_000, 10_000, 25_000, 50_000, 100_000}


def _should_notify_new_user(total: int) -> bool:
    return total <= 50 or total in _MILESTONES


def _milestone_label(total: int) -> int | None:
    return total if total in _MILESTONES else None


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
        if discord_api.is_configured():
            try:
                total = User.objects.count()
                if _should_notify_new_user(total):
                    discord_api.notify_superusers_new_user(
                        new_username=instance.username,
                        total_users=total,
                        milestone=_milestone_label(total),
                    )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning('new user discord notify failed: %s', exc)
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