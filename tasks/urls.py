# tasks/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('mine/', views.my_tasks, name='my_tasks'),
    path('new/', views.task_create, name='task_create'),
    path('slug-available/', views.slug_available, name='task_slug_available'),
    path('reorder/', views.task_reorder, name='task_reorder'),
    path('<slug:task_slug>/edit/', views.task_edit, name='task_edit'),
    path('<slug:task_slug>/delete/', views.task_delete, name='task_delete'),
    path('<slug:task_slug>/unpublish/', views.task_unpublish, name='task_unpublish'),
    path('<slug:task_slug>/publish/', views.task_publish, name='task_publish'),
]
