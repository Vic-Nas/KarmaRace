from django.contrib import admin

from accounts.models import User, VerifiedEmail
admin.site.register(User)
admin.site.register(VerifiedEmail)
