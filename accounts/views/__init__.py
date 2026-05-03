# accounts/views/__init__.py
"""Accounts views package."""
from .linked import linked_accounts, connect_account, discord_entry, discord_callback, unlink_account
from .email import verify_email_start, verify_email_callback, remove_verified_email
from .preferences import preferences
from .profile import edit_profile, public_profile
from .verify import verify_karmarace_hook
from .username import pick_username, username_check

__all__ = [
    'linked_accounts', 'connect_account', 'discord_entry', 'discord_callback', 'unlink_account',
    'verify_email_start', 'verify_email_callback', 'remove_verified_email',
    'preferences',
    'edit_profile', 'public_profile',
    'verify_karmarace_hook',
    'pick_username', 'username_check',
]
