from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from karma.models import KarmaTransaction


@admin.register(KarmaTransaction)
class KarmaTransactionAdmin(admin.ModelAdmin):
    list_display  = ('user_link', 'delta', 'reason', 'created_at')
    list_filter   = ('reason', 'created_at')
    search_fields = ('user__username', 'user__email')
    ordering      = ('-created_at',)
    readonly_fields = ('user', 'delta', 'reason', 'related_object_id', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def user_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'


