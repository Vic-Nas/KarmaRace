# accounts/views/preferences.py
"""User preferences view."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from accounts.models import LinkedAccount, UserPreference
from notifications.models import Notification, NotificationPreference
from setup.platform_rules import KARMA_HIGH_THRESHOLD, KARMA_LOW_THRESHOLD


@login_required
def preferences(request):
	"""Manage user notification and karma threshold preferences."""
	if request.method == 'POST':
		try:
			low_value  = int((request.POST.get('karma_low_threshold')  or '').strip())
			high_value = int((request.POST.get('karma_high_threshold') or '').strip())
			if low_value < 0 or high_value < 0:
				raise ValueError('Thresholds must be non-negative.')
			if high_value <= low_value:
				raise ValueError('High threshold must be greater than low threshold.')
		except ValueError as exc:
			messages.error(request, str(exc))
			return redirect('preferences')

		UserPreference.objects.update_or_create(
			user=request.user, key='karma_low_threshold',  defaults={'value': str(low_value)},
		)
		UserPreference.objects.update_or_create(
			user=request.user, key='karma_high_threshold', defaults={'value': str(high_value)},
		)

		if request.user.is_pro:
			webhook_url    = (request.POST.get('webhook_url')    or '').strip()
			webhook_secret = (request.POST.get('webhook_secret') or '').strip()
			for event, _ in Notification.Event.choices:
				webhook_on = request.POST.get(f'webhook_{event}') == '1'
				discord_on = request.POST.get(f'discord_{event}') == '1'
				defaults   = {
					'webhook_url':     webhook_url if webhook_on else '',
					'discord_enabled': discord_on,
				}
				if hasattr(NotificationPreference, 'webhook_secret'):
					defaults['webhook_secret'] = webhook_secret if webhook_on else ''
				NotificationPreference.objects.update_or_create(
					user=request.user, event=event, defaults=defaults,
				)

		messages.success(request, 'Preferences saved.')
		return redirect('preferences')

	prefs = {}
	webhook_url = webhook_secret = ''
	if request.user.is_pro:
		for pref in NotificationPreference.objects.filter(user=request.user):
			prefs[pref.event] = pref
			if not webhook_url and pref.webhook_url:
				webhook_url = pref.webhook_url
			if not webhook_secret and getattr(pref, 'webhook_secret', ''):
				webhook_secret = pref.webhook_secret

	low_pref  = UserPreference.objects.filter(user=request.user, key='karma_low_threshold').first()
	high_pref = UserPreference.objects.filter(user=request.user, key='karma_high_threshold').first()
	has_discord = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.DISCORD).exists()

	return render(request, 'accounts/preferences.html', {
		'prefs':         prefs,
		'webhook_url':   webhook_url,
		'webhook_secret': webhook_secret,
		'all_events':    Notification.Event.choices,
		'low_threshold':  low_pref.value  if low_pref  else str(KARMA_LOW_THRESHOLD),
		'high_threshold': high_pref.value if high_pref else str(KARMA_HIGH_THRESHOLD),
		'has_discord':   has_discord,
	})
