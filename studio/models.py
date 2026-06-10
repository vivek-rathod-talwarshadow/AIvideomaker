from django.db import models
from django.utils import timezone

from .enums import AssetType, ContentNiche, JobStatus, PlatformType


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ChannelProfile(TimeStampedModel):
    name = models.CharField(max_length=120)
    platform = models.CharField(max_length=20, choices=PlatformType.choices)
    is_active = models.BooleanField(default=True)
    credential_key = models.CharField(max_length=120, blank=True)
    default_hashtags = models.TextField(blank=True)
    rate_limit_per_day = models.PositiveIntegerField(default=2)
    cooldown_minutes = models.PositiveIntegerField(default=60)

    def __str__(self) -> str:
        return f"{self.get_platform_display()} - {self.name}"


class ContentTemplate(TimeStampedModel):
    name = models.CharField(max_length=120)
    niche = models.CharField(max_length=40, choices=ContentNiche.choices)
    hook_template = models.CharField(max_length=240)
    intro_template = models.TextField()
    body_template = models.TextField()
    outro_template = models.TextField(blank=True)
    emoji_style = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class ViralTopic(TimeStampedModel):
    niche = models.CharField(max_length=40, choices=ContentNiche.choices)
    title = models.CharField(max_length=240)
    hook = models.CharField(max_length=240)
    script = models.TextField()
    scene_plan = models.JSONField(default=list, blank=True)
    seo_title = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    hashtags = models.JSONField(default=list, blank=True)
    source_notes = models.JSONField(default=list, blank=True)
    is_trending = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.title


class VideoProject(TimeStampedModel):
    topic = models.ForeignKey(ViralTopic, on_delete=models.CASCADE, related_name="projects")
    niche = models.CharField(max_length=40, choices=ContentNiche.choices)
    voice_name = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=JobStatus.choices, default=JobStatus.DRAFT)
    aspect_ratio = models.CharField(max_length=20, default="9:16")
    target_width = models.PositiveIntegerField(default=1080)
    target_height = models.PositiveIntegerField(default=1920)
    duration_seconds = models.PositiveIntegerField(default=30)
    caption_style = models.JSONField(default=dict, blank=True)
    output_file = models.CharField(max_length=255, blank=True)
    subtitle_file = models.CharField(max_length=255, blank=True)
    voiceover_file = models.CharField(max_length=255, blank=True)
    music_file = models.CharField(max_length=255, blank=True)
    content_signature = models.CharField(max_length=40, blank=True)
    output_fingerprint = models.CharField(max_length=40, blank=True)
    failure_reason = models.TextField(blank=True)
    progress_percent = models.PositiveIntegerField(default=0)
    status_message = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"{self.topic.title} [{self.status}]"


class MediaAsset(TimeStampedModel):
    project = models.ForeignKey(VideoProject, on_delete=models.CASCADE, related_name="assets")
    asset_type = models.CharField(max_length=20, choices=AssetType.choices)
    source_url = models.URLField(blank=True)
    local_path = models.CharField(max_length=255)
    credit = models.CharField(max_length=240, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.asset_type} - {self.local_path}"


class PublishJob(TimeStampedModel):
    project = models.ForeignKey(VideoProject, on_delete=models.CASCADE, related_name="publish_jobs")
    channel = models.ForeignKey(ChannelProfile, on_delete=models.CASCADE, related_name="jobs")
    status = models.CharField(max_length=20, choices=JobStatus.choices, default=JobStatus.QUEUED)
    scheduled_for = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    remote_post_id = models.CharField(max_length=255, blank=True)
    last_error = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["scheduled_for", "order_index", "created_at"]

    def __str__(self) -> str:
        return f"{self.channel} -> {self.project}"


class SchedulerLock(TimeStampedModel):
    key = models.CharField(max_length=80, unique=True)
    locked_until = models.DateTimeField()
    owner = models.CharField(max_length=120, blank=True)

    def __str__(self) -> str:
        return self.key


class AutomationState(TimeStampedModel):
    key = models.CharField(max_length=80, unique=True, default="global")
    default_voice_name = models.CharField(max_length=80, default="en-US-ChristopherNeural")
    brainrot_mode = models.BooleanField(default=True)
    selected_niches = models.JSONField(default=list, blank=True)
    is_enabled = models.BooleanField(default=True)
    auto_upload = models.BooleanField(default=True)
    retry_failures = models.BooleanField(default=True)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_paused_at = models.DateTimeField(null=True, blank=True)
    last_cycle_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.key} ({'enabled' if self.is_enabled else 'paused'})"


class EventLog(TimeStampedModel):
    level = models.CharField(max_length=20, default="info")
    event_type = models.CharField(max_length=80)
    project = models.ForeignKey(VideoProject, null=True, blank=True, on_delete=models.SET_NULL)
    publish_job = models.ForeignKey(PublishJob, null=True, blank=True, on_delete=models.SET_NULL)
    message = models.TextField()
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.level}: {self.event_type}"
