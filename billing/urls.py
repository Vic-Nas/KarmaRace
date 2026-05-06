# billing/urls.py
from django.urls import path
from billing import views

urlpatterns = [
    path('plan/', views.billing_plan, name='billing_plan'),
    path('portal/', views.billing_portal, name='billing_portal'),
]
