# karma/admin.py
from django.contrib import admin
from .models import KarmaTransaction, KarmaConfig

admin.site.register(KarmaTransaction)
admin.site.register(KarmaConfig)