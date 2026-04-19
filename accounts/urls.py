# accounts/urls.py
from django.urls import path
from . import views

urlpatterns = [
	path('preferences/', views.preferences, name='preferences'),
	path('linked-accounts/', views.linked_accounts, name='linked_accounts'),
	path('discord/', views.discord_entry, name='discord_entry'),
	path('discord/callback/', views.discord_callback, name='discord_callback'),
	path('linked-accounts/connect/<str:platform>/', views.connect_account, name='connect_account'),
	path('linked-accounts/github/connect/', views.github_connect, name='github_connect'),
	path('linked-accounts/<str:platform>/unlink/', views.unlink_account, name='unlink_account'),
]