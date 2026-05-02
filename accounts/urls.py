# accounts/urls.py
from django.urls import path
from . import views

urlpatterns = [
	path('preferences/', views.preferences, name='preferences'),
	path('linked-accounts/', views.linked_accounts, name='linked_accounts'),
	path('discord/', views.discord_entry, name='discord_entry'),
	path('discord/callback/', views.discord_callback, name='discord_callback'),
	path('linked-accounts/connect/<str:platform>/', views.connect_account, name='connect_account'),
	path('linked-accounts/<str:platform>/unlink/', views.unlink_account, name='unlink_account'),
	path('verified-emails/verify/', views.verify_email_start, name='verify_email_start'),
	path('verified-emails/callback/', views.verify_email_callback, name='verify_email_callback'),
	path('verified-emails/<int:email_id>/remove/', views.remove_verified_email, name='remove_verified_email'),
	path('profile/edit/', views.edit_profile, name='edit_profile'),
	path('verify/', views.verify_karmarace_hook, name='verify_karmarace_hook'),
]
