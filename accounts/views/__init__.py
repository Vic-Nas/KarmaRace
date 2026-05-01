"""Accounts views package."""
from .linked import linked_accounts, connect_account, discord_entry, discord_callback, unlink_account
from .email import verify_email_start, verify_email_callback, remove_verified_email
from .preferences import preferences
from .profile import edit_profile, public_profile

__all__ = [
	'linked_accounts', 'connect_account', 'discord_entry', 'discord_callback', 'unlink_account',
	'verify_email_start', 'verify_email_callback', 'remove_verified_email',
	'preferences',
	'edit_profile', 'public_profile',
]
