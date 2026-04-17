# projects/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('new/', views.project_create, name='project_create'),
    path('<int:pk>/', views.project_detail_legacy, name='project_detail_legacy'),
    path('<int:pk>/edit/', views.project_edit_legacy, name='project_edit_legacy'),
    path('<slug:slug>/', views.project_detail, name='project_detail'),
    path('<slug:slug>/edit/', views.project_edit, name='project_edit'),
    path('<slug:slug>/state/', views.project_update_state, name='project_update_state'),
    path('<slug:slug>/url/', views.project_update_url, name='project_update_url'),
]