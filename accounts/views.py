from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from accounts.models import LinkedAccount


@login_required
def linked_accounts(request):
	if request.method == 'POST':
		platform = (request.POST.get('platform') or '').strip()
		username = (request.POST.get('platform_username') or '').strip()
		platform_id = (request.POST.get('platform_id') or '').strip()
		access_token = (request.POST.get('access_token') or '').strip()

		if platform not in {LinkedAccount.GITHUB, LinkedAccount.PRODUCTHUNT}:
			messages.error(request, 'Invalid platform selection.')
			return redirect('linked_accounts')

		if platform == LinkedAccount.GITHUB and not username:
			messages.error(request, 'GitHub username is required.')
			return redirect('linked_accounts')

		if platform == LinkedAccount.PRODUCTHUNT and not access_token:
			messages.error(request, 'Product Hunt access token is required.')
			return redirect('linked_accounts')

		if not platform_id:
			# Keep a stable fallback when platform user id is unknown.
			platform_id = username or f'{platform}-{request.user.pk}'

		LinkedAccount.objects.update_or_create(
			user=request.user,
			platform=platform,
			defaults={
				'platform_username': username,
				'platform_id': platform_id,
				'access_token': access_token,
			},
		)
		messages.success(request, f'{platform.title()} link saved.')
		return redirect('linked_accounts')

	github = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.GITHUB).first()
	producthunt = LinkedAccount.objects.filter(user=request.user, platform=LinkedAccount.PRODUCTHUNT).first()

	return render(request, 'accounts/linked_accounts.html', {
		'github': github,
		'producthunt': producthunt,
	})

