# accounts/outreach/email.py
"""Email template builders for outreach."""

from django.template.loader import render_to_string


def _build_context(domain: str) -> dict:
	root = "https://" + domain
	return {
		"root": root,
		"help_href": root + "/help",
		"priv_href": root + "/legal/privacy",
	}


def build_html(domain: str) -> str:
	"""Build HTML email template."""
	return render_to_string("outreach/email.html", _build_context(domain))


def build_plaintext(domain: str) -> str:
	"""Build plaintext email template."""
	return render_to_string("outreach/email.txt", _build_context(domain))
