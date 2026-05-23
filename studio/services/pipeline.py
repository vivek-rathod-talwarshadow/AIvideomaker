from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from socket import gethostname

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from studio.enums import JobStatus, PlatformType
from studio.models import ChannelProfile, PublishJob, SchedulerLock, VideoProject
from .logging_service import log_event
from .renderer import render_slideshow_video
from .source_fetcher import fetch_placeholder_assets
from .subtitles import generate_basic_srt
from .topic_generator import build_rule_based_topic
from .uploaders import get_uploader
from .utils import safe_rmtree, safe_unlink
from .voiceover import generate_voiceover


def acquire_lock(key: str) -> bool:
    now = timezone.now()
    ttl = now + timedelta(seconds=settings.JOB_LOCK_TTL_SECONDS)
    with transaction.atomic():
        lock = SchedulerLock.objects.select_for_update().filter(key=key).first()
        if lock and lock.locked_until > now:
            return False
        if not lock:
            SchedulerLock.objects.create(key=key, locked_until=ttl, owner=gethostname())
        else:
            lock.locked_until = ttl
            lock.owner = gethostname()
            lock.save(update_fields=["locked_until", "owner", "updated_at"])
    return True


def release_lock(key: str) -> None:
    SchedulerLock.objects.filter(key=key).update(locked_until=timezone.now())


def get_enabled_platforms() -> list[str]:
    platforms: list[str] = []
    if settings.ENABLE_YOUTUBE_UPLOAD:
        platforms.append(PlatformType.YOUTUBE)
    if settings.ENABLE_INSTAGRAM_UPLOAD:
        platforms.append(PlatformType.INSTAGRAM)
    if settings.ENABLE_PINTEREST_UPLOAD:
        platforms.append(PlatformType.PINTEREST)
    return platforms


def is_platform_enabled(platform: str) -> bool:
    return platform in get_enabled_platforms()


def get_or_create_default_channel(platform: str) -> ChannelProfile:
    defaults = {
        PlatformType.YOUTUBE: "YouTube Shorts",
        PlatformType.INSTAGRAM: "Instagram Reels",
        PlatformType.PINTEREST: "Pinterest Idea Pins",
    }
    channel, _ = ChannelProfile.objects.get_or_create(
        platform=platform,
        name=defaults[platform],
        defaults={"is_active": True},
    )
    return channel


def create_daily_project_if_needed() -> VideoProject | None:
    today = timezone.localdate()
    created_today = VideoProject.objects.filter(created_at__date=today).count()
    if created_today >= settings.MAX_VIDEOS_PER_DAY:
        return None

    topic = build_rule_based_topic("facts")
    project = VideoProject.objects.create(
        topic=topic,
        niche=topic.niche,
        status=JobStatus.QUEUED,
        caption_style={
            "font_size": 60,
            "stroke": 4,
            "highlight_color": "#F9D423",
            "text_color": "#FFFFFF",
            "position": "bottom-third",
        },
    )
    fetch_placeholder_assets(project)
    enabled_platforms = get_enabled_platforms()
    for order_index, platform in enumerate(enabled_platforms, start=1):
        channel = get_or_create_default_channel(platform)
        PublishJob.objects.create(
            project=project,
            channel=channel,
            scheduled_for=timezone.now() + timedelta(minutes=(order_index - 1) * 20),
            order_index=order_index,
        )
    if not enabled_platforms:
        project.status = JobStatus.SKIPPED
        project.failure_reason = "No platforms are enabled."
        project.save(update_fields=["status", "failure_reason", "updated_at"])
    log_event("project.created", "Daily project generated.", project=project)
    return project


def create_project(niche: str = "facts") -> VideoProject:
    topic = build_rule_based_topic(niche)
    project = VideoProject.objects.create(
        topic=topic,
        niche=topic.niche,
        status=JobStatus.QUEUED,
        caption_style={
            "font_size": 60,
            "stroke": 4,
            "highlight_color": "#F9D423",
            "text_color": "#FFFFFF",
            "position": "bottom-third",
        },
    )
    fetch_placeholder_assets(project)
    enabled_platforms = get_enabled_platforms()
    for order_index, platform in enumerate(enabled_platforms, start=1):
        channel = get_or_create_default_channel(platform)
        PublishJob.objects.create(
            project=project,
            channel=channel,
            scheduled_for=timezone.now() + timedelta(minutes=(order_index - 1) * 20),
            order_index=order_index,
        )
    if not enabled_platforms:
        project.status = JobStatus.SKIPPED
        project.failure_reason = "No platforms are enabled."
        project.save(update_fields=["status", "failure_reason", "updated_at"])
    log_event("project.created", "Manual project generated from dashboard.", project=project)
    return project


def generate_project_media(project: VideoProject) -> None:
    project.status = JobStatus.GENERATING
    project.save(update_fields=["status", "updated_at"])
    generate_voiceover(project)
    generate_basic_srt(project)
    render_slideshow_video(project)
    log_event("project.rendered", "Project assets and video generated.", project=project)


def purge_project_media(project: VideoProject) -> None:
    for asset in project.assets.all():
        if asset.local_path:
            safe_unlink(asset.local_path)

    for path in [project.voiceover_file, project.subtitle_file, project.music_file, project.output_file]:
        if path:
            safe_unlink(path)

    project_root = Path(settings.MEDIA_ROOT) / "projects" / str(project.id)
    safe_rmtree(project_root)
    project.output_file = ""
    project.voiceover_file = ""
    project.subtitle_file = ""
    project.music_file = ""
    project.save(update_fields=["output_file", "voiceover_file", "subtitle_file", "music_file", "updated_at"])


def publish_next_job() -> PublishJob | None:
    now = timezone.now()
    job = (
        PublishJob.objects.select_related("project", "channel")
        .filter(status=JobStatus.QUEUED, scheduled_for__lte=now)
        .order_by("scheduled_for", "order_index", "created_at")
        .first()
    )
    if not job:
        return None
    if not is_platform_enabled(job.channel.platform):
        job.status = JobStatus.SKIPPED
        job.last_error = f"{job.channel.get_platform_display()} is disabled in settings."
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
        log_event("publish.skipped", job.last_error, project=job.project, publish_job=job)
        return job

    blockers = PublishJob.objects.filter(
        project=job.project,
        order_index__lt=job.order_index,
    ).exclude(status=JobStatus.POSTED)
    if blockers.exists():
        return None

    try:
        if job.project.status not in [JobStatus.READY, JobStatus.POSTING, JobStatus.POSTED]:
            generate_project_media(job.project)

        job.status = JobStatus.POSTING
        job.started_at = now
        job.save(update_fields=["status", "started_at", "updated_at"])

        result = get_uploader(job.channel.platform).upload(job)
        job.status = result.status
        job.remote_post_id = result.remote_post_id
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "remote_post_id", "finished_at", "updated_at"])
        log_event("publish.success", f"Uploaded to {job.channel.platform}.", project=job.project, publish_job=job)

        if not job.project.publish_jobs.exclude(status=JobStatus.POSTED).exists():
            job.project.status = JobStatus.POSTED
            job.project.save(update_fields=["status", "updated_at"])
            purge_project_media(job.project)
        return job
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.retry_count += 1
        job.last_error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "retry_count", "last_error", "finished_at", "updated_at"])
        job.project.status = JobStatus.FAILED
        job.project.failure_reason = str(exc)
        job.project.save(update_fields=["status", "failure_reason", "updated_at"])
        purge_project_media(job.project)
        log_event("publish.failed", str(exc), level="error", project=job.project, publish_job=job)
        return job


def generate_latest_project() -> VideoProject | None:
    project = VideoProject.objects.order_by("-created_at").first()
    if not project:
        return None
    if project.status in [JobStatus.POSTED, JobStatus.POSTING]:
        return project
    generate_project_media(project)
    return project


def publish_project(project: VideoProject) -> PublishJob | None:
    job = (
        project.publish_jobs.select_related("channel")
        .filter(status__in=[JobStatus.QUEUED, JobStatus.FAILED, JobStatus.SKIPPED])
        .order_by("order_index", "created_at")
        .first()
    )
    if not job:
        return None

    if job.status in [JobStatus.FAILED, JobStatus.SKIPPED]:
        job.status = JobStatus.QUEUED
        job.last_error = ""
        job.finished_at = None
        job.scheduled_for = timezone.now()
        job.save(update_fields=["status", "last_error", "finished_at", "scheduled_for", "updated_at"])

    if job.scheduled_for > timezone.now():
        job.scheduled_for = timezone.now()
        job.save(update_fields=["scheduled_for", "updated_at"])

    return publish_next_job()


def process_due_work() -> dict:
    if not acquire_lock("pipeline"):
        return {"ok": True, "detail": "pipeline-locked"}

    try:
        project = create_daily_project_if_needed()
        job = publish_next_job()
        return {
            "ok": True,
            "created_project_id": getattr(project, "id", None),
            "processed_job_id": getattr(job, "id", None),
        }
    finally:
        release_lock("pipeline")
