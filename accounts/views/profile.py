# accounts/views/profile.py
"""Profile editing and public profile views."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404

from accounts.models import UserProfile


@login_required
def edit_profile(request):
	"""Edit user profile information and visibility settings."""
	profile, _ = UserProfile.objects.get_or_create(user=request.user)

	if request.method == 'POST':
		profile.first_name = (request.POST.get('first_name') or '').strip()[:100]
		profile.last_name = (request.POST.get('last_name') or '').strip()[:100]
		profile.contact_email = (request.POST.get('contact_email') or '').strip()[:254]
		profile.show_first_name = request.POST.get('show_first_name') == '1'
		profile.show_last_name = request.POST.get('show_last_name') == '1'
		profile.show_contact_email = request.POST.get('show_contact_email') == '1'
		profile.show_github = request.POST.get('show_github') == '1'
		profile.show_karma = request.POST.get('show_karma') == '1'
		profile.show_joined = request.POST.get('show_joined') == '1'
		profile.save()
		messages.success(request, 'Profile saved.')
		return redirect('edit_profile')

	visibility_fields = [
		('show_first_name', 'First name', profile.show_first_name),
		('show_last_name', 'Last name', profile.show_last_name),
		('show_contact_email', 'Contact email', profile.show_contact_email),
		('show_github', 'GitHub link', profile.show_github),
		('show_karma', 'Karma balance', profile.show_karma),
		('show_joined', 'Member since', profile.show_joined),
	]

	return render(request, 'accounts/edit_profile.html', {
		'profile': profile,
		'visibility_fields': visibility_fields,
	})


def public_profile(request, username):
	"""Display a user's public profile."""
	from django.contrib.auth import get_user_model
	from karma.services import get_balance
	from tasks.models import Task, TaskCompletion

	User = get_user_model()
	profile_user = get_object_or_404(User, username=username)
	profile, _   = UserProfile.objects.get_or_create(user=profile_user)
	is_own       = request.user.is_authenticated and request.user == profile_user

	karma           = get_balance(profile_user)
	task_count      = Task.objects.filter(owner=profile_user, is_deleted=False).count()
	completed_count = TaskCompletion.objects.filter(
		tester=profile_user, state=TaskCompletion.State.CONFIRMED,
	).count()
	
	from accounts.models import LinkedAccount
	github = LinkedAccount.objects.filter(user=profile_user, platform=LinkedAccount.GITHUB).first()

	return render(request, 'accounts/profile.html', {
		'profile_user':     profile_user,
		'profile':          profile,
		'karma':            karma if (profile.show_karma or is_own) else None,
		'task_count':       task_count,
		'completed_count':  completed_count,
		'github':           github if (profile.show_github or is_own) else None,
		'is_own':           is_own,
	})
