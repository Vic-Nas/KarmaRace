# accounts/urls.py
from django.urls import path
from . import views

urlpatterns = [
	path('linked-accounts/', views.linked_accounts, name='linked_accounts'),
]