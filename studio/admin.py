from django.contrib import admin, messages
from django.utils import timezone

from .models import ChannelProfile, ContentTemplate, EventLog, MediaAsset, PublishJob, SchedulerLock, VideoProject, ViralTopic


@admin.register(ChannelProfile)
class ChannelProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "platform", "is_active", "rate_limit_per_day", "cooldown_minutes")
    list_filter = ("platform", "is_active")


@admin.register(ContentTemplate)
class ContentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "niche", "is_active", "updated_at")
    list_filter = ("niche", "is_active")
    search_fields = ("name", "hook_template")


class MediaAssetInline(admin.TabularInline):
    model = MediaAsset
    extra = 0


@admin.register(ViralTopic)
class ViralTopicAdmin(admin.ModelAdmin):
    list_display = ("title", "niche", "is_trending", "created_at")
    list_filter = ("niche", "is_trending")
    search_fields = ("title", "hook", "script")


@admin.action(description="Retry selected publish jobs")
def retry_jobs(modeladmin, request, queryset):
    updated = queryset.update(
        status="queued",
        scheduled_for=timezone.now(),
        last_error="",
    )
    modeladmin.message_user(request, f"Queued {updated} jobs for retry.", level=messages.SUCCESS)


@admin.register(VideoProject)
class VideoProjectAdmin(admin.ModelAdmin):
    list_display = ("topic", "niche", "status", "duration_seconds", "updated_at")
    list_filter = ("niche", "status")
    search_fields = ("topic__title",)
    inlines = [MediaAssetInline]


@admin.register(PublishJob)
class PublishJobAdmin(admin.ModelAdmin):
    list_display = ("project", "channel", "status", "scheduled_for", "retry_count", "order_index")
    list_filter = ("status", "channel__platform")
    search_fields = ("project__topic__title", "remote_post_id")
    actions = [retry_jobs]


@admin.register(EventLog)
class EventLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "event_type", "project", "publish_job")
    list_filter = ("level", "event_type")
    search_fields = ("message",)


@admin.register(SchedulerLock)
class SchedulerLockAdmin(admin.ModelAdmin):
    list_display = ("key", "locked_until", "owner", "updated_at")
