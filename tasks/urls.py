# tasks/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('mine/', views.my_tasks, name='my_tasks'),
    path('new/', views.task_create, name='task_create'),
    path('<int:task_pk>/edit/', views.task_edit, name='task_edit'),
    path('<int:task_pk>/delete/', views.task_delete, name='task_delete'),
    path('<int:task_pk>/unpublish/', views.task_unpublish, name='task_unpublish'),
    path('<int:task_pk>/publish/', views.task_publish, name='task_publish'),
]