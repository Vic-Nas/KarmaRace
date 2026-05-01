from django.contrib import admin

from accounts.models import (
    User,
    VerifiedEmail,
    OutreachRecord,
    OutreachContactedEmail,
    OutreachDailyStats,
)

admin.site.register(User)
admin.site.register(VerifiedEmail)


@admin.register(OutreachRecord)
class OutreachRecordAdmin(admin.ModelAdmin):
    list_display  = ("email", "score", "created_at")
    list_filter   = ("created_at",)
    search_fields = ("email",)
    ordering      = ("-score", "created_at")


@admin.register(OutreachContactedEmail)
class OutreachContactedEmailAdmin(admin.ModelAdmin):
    list_display  = ("email", "contacted_at")
    search_fields = ("email",)
    ordering      = ("-contacted_at",)


@admin.register(OutreachDailyStats)
class OutreachDailyStatsAdmin(admin.ModelAdmin):
    list_display = (
        "date", "harvested", "queued_count", "sent_count",
        "failed_count", "pending_after", "updated_at",
    )
    ordering = ("-date",)
