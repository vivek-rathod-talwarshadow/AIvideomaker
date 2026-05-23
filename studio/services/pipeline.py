from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from socket import gethostname
import threading

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from studio.enums import JobStatus, PlatformType
from studio.models import AutomationState, ChannelProfile, PublishJob, SchedulerLock, VideoProject
from .logging_service import log_event
from .renderer import render_slideshow_video
from .source_fetcher import fetch_scene_assets
from .subtitles import generate_basic_srt
from .topic_generator import build_rule_based_topic, estimate_duration_seconds
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


def set_project_progress(project: VideoProject, percent: int, message: str) -> None:
    project.progress_percent = max(0, min(100, percent))
    project.status_message = message[:255]
    project.save(update_fields=["progress_percent", "status_message", "updated_at"])


def youtube_upload_configured() -> bool:
    return all(
        [
            getattr(settings, "YOUTUBE_CLIENT_ID", ""),
            getattr(settings, "YOUTUBE_CLIENT_SECRET", ""),
            getattr(settings, "YOUTUBE_REFRESH_TOKEN", ""),
        ]
    )


def get_automation_state() -> AutomationState:
    state, _ = AutomationState.objects.get_or_create(
        key="global",
        defaults={
            "is_enabled": True,
            "auto_upload": True,
            "retry_failures": True,
            "last_started_at": timezone.now(),
        },
    )
    return state


def start_automation() -> AutomationState:
    state = get_automation_state()
    state.is_enabled = True
    state.auto_upload = True
    state.last_started_at = timezone.now()
    state.last_error = ""
    state.save(update_fields=["is_enabled", "auto_upload", "last_started_at", "last_error", "updated_at"])
    log_event("automation.started", "Automation started from dashboard.")
    return state


def pause_automation() -> AutomationState:
    state = get_automation_state()
    state.is_enabled = False
    state.last_paused_at = timezone.now()
    state.save(update_fields=["is_enabled", "last_paused_at", "updated_at"])
    log_event("automation.paused", "Automation paused from dashboard.")
    return state


def _schedule_retry(job: PublishJob, exc: Exception) -> PublishJob:
    state = get_automation_state()
    retry_limit = max(0, settings.AUTOMATION_RETRY_LIMIT)
    next_retry = timezone.now() + timedelta(seconds=settings.AUTOMATION_RETRY_DELAY_SECONDS)
    job.retry_count += 1
    job.last_error = str(exc)
    job.finished_at = timezone.now()

    project = job.project
    project.status = JobStatus.FAILED
    project.failure_reason = str(exc)
    project.status_message = "Generation or upload failed."
    project.progress_percent = 100
    project.save(update_fields=["status", "failure_reason", "status_message", "progress_percent", "updated_at"])
    purge_project_media(project)

    should_retry = state.retry_failures and job.retry_count <= retry_limit
    if should_retry:
        job.status = JobStatus.QUEUED
        job.finished_at = None
        job.scheduled_for = next_retry
        job.save(update_fields=["status", "retry_count", "last_error", "finished_at", "scheduled_for", "updated_at"])
        project.status = JobStatus.QUEUED
        project.status_message = f"Retrying automatically in {settings.AUTOMATION_RETRY_DELAY_SECONDS} seconds."
        project.progress_percent = 0
        project.save(update_fields=["status", "status_message", "progress_percent", "updated_at"])
        log_event(
            "automation.retry_scheduled",
            f"Retry {job.retry_count}/{retry_limit} scheduled after failure: {exc}",
            level="error",
            project=project,
            publish_job=job,
        )
    else:
        job.status = JobStatus.FAILED
        job.save(update_fields=["status", "retry_count", "last_error", "finished_at", "updated_at"])
        log_event("publish.failed", str(exc), level="error", project=project, publish_job=job)
        delete_project_record(project, reason="final failure")
    return job


def get_enabled_platforms() -> list[str]:
    platforms: list[str] = []
    if settings.ENABLE_YOUTUBE_UPLOAD and youtube_upload_configured():
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
        PlatformType.YOUTUBE: settings.CHANNEL_BRAND_NAME,
        PlatformType.INSTAGRAM: "Instagram Reels",
        PlatformType.PINTEREST: "Pinterest Idea Pins",
    }
    channel = ChannelProfile.objects.filter(platform=platform).order_by("id").first()
    if channel:
        expected_name = defaults[platform]
        if channel.name != expected_name:
            channel.name = expected_name
            channel.save(update_fields=["name", "updated_at"])
        return channel
    channel = ChannelProfile.objects.create(platform=platform, name=defaults[platform], is_active=True)
    return channel


def create_daily_project_if_needed() -> VideoProject | None:
    today = timezone.localdate()
    created_today = VideoProject.objects.filter(created_at__date=today).count()
    if created_today >= settings.MAX_VIDEOS_PER_DAY:
        return None
    enabled_platforms = get_enabled_platforms()
    if not enabled_platforms:
        log_event(
            "automation.skipped",
            "Automation did not create a project because no upload platform is fully configured.",
            level="error",
        )
        return None

    topic = build_rule_based_topic("facts")
    duration_seconds = estimate_duration_seconds(topic.script, topic.scene_plan)
    project = VideoProject.objects.create(
        topic=topic,
        niche=topic.niche,
        status=JobStatus.QUEUED,
        duration_seconds=duration_seconds,
        progress_percent=5,
        status_message="Project created and waiting to generate.",
        caption_style={
            "font_size": 60,
            "stroke": 4,
            "highlight_color": "#F9D423",
            "text_color": "#FFFFFF",
            "position": "bottom-third",
            "brand_name": settings.CHANNEL_BRAND_NAME,
        },
    )
    fetch_scene_assets(project)
    for order_index, platform in enumerate(enabled_platforms, start=1):
        channel = get_or_create_default_channel(platform)
        PublishJob.objects.create(
            project=project,
            channel=channel,
            scheduled_for=timezone.now() + timedelta(minutes=(order_index - 1) * 20),
            order_index=order_index,
        )
    log_event("automation.project_queued", "Project queued for automatic generation and upload.", project=project)
    log_event(
        "project.created",
        "Daily project generated.",
        project=project,
        payload={"title": project.topic.title, "niche": project.niche, "automation": True},
    )
    return project


def create_project(niche: str = "facts") -> VideoProject:
    topic = build_rule_based_topic(niche)
    duration_seconds = estimate_duration_seconds(topic.script, topic.scene_plan)
    project = VideoProject.objects.create(
        topic=topic,
        niche=topic.niche,
        status=JobStatus.QUEUED,
        duration_seconds=duration_seconds,
        caption_style={
            "font_size": 60,
            "stroke": 4,
            "highlight_color": "#F9D423",
            "text_color": "#FFFFFF",
            "position": "bottom-third",
            "brand_name": settings.CHANNEL_BRAND_NAME,
        },
    )
    fetch_scene_assets(project)
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
    log_event(
        "project.created",
        "Manual project generated from dashboard.",
        project=project,
        payload={"title": project.topic.title, "niche": project.niche, "automation": False},
    )
    return project


def ensure_publish_jobs(project: VideoProject) -> list[PublishJob]:
    existing_jobs = list(project.publish_jobs.select_related("channel").order_by("order_index", "created_at"))
    if existing_jobs:
        return existing_jobs

    enabled_platforms = get_enabled_platforms()
    jobs: list[PublishJob] = []
    for order_index, platform in enumerate(enabled_platforms, start=1):
        channel = get_or_create_default_channel(platform)
        jobs.append(
            PublishJob.objects.create(
                project=project,
                channel=channel,
                scheduled_for=timezone.now() + timedelta(minutes=(order_index - 1) * 20),
                order_index=order_index,
            )
        )
    if jobs:
        log_event("publish.jobs_created", "Missing publish jobs were recreated automatically.", project=project)
    return jobs


def generate_project_media(project: VideoProject) -> None:
    project.status = JobStatus.GENERATING
    project.failure_reason = ""
    project.duration_seconds = estimate_duration_seconds(project.topic.script, project.topic.scene_plan)
    project.save(update_fields=["status", "failure_reason", "duration_seconds", "updated_at"])
    set_project_progress(project, 15, "Preparing scene assets...")
    should_refresh_assets = (not project.assets.exists()) or not project.assets.filter(
        metadata__placeholder=False
    ).exists()
    if should_refresh_assets:
        fetch_scene_assets(project, replace_existing=project.assets.exists())
    set_project_progress(project, 35, "Generating voiceover...")
    log_event("project.voiceover_started", "Generating AI voiceover.", project=project)
    generate_voiceover(project)
    set_project_progress(project, 55, "Building subtitles...")
    generate_basic_srt(project)
    set_project_progress(project, 75, "Rendering slideshow video...")
    log_event("project.render_started", "Rendering animated video with captions.", project=project)
    render_slideshow_video(project)
    set_project_progress(project, 100, "Preview ready for upload.")
    log_event("project.rendered", "Project assets and video generated.", project=project)


def purge_project_media(project: VideoProject) -> bool:
    cleanup_ok = True
    for asset in project.assets.all():
        if asset.local_path:
            cleanup_ok = safe_unlink(asset.local_path) and cleanup_ok

    for path in [project.voiceover_file, project.subtitle_file, project.music_file, project.output_file]:
        if path:
            cleanup_ok = safe_unlink(path) and cleanup_ok

    project_root = Path(settings.MEDIA_ROOT) / "projects" / str(project.id)
    cleanup_ok = safe_rmtree(project_root) and cleanup_ok
    project.output_file = ""
    project.voiceover_file = ""
    project.subtitle_file = ""
    project.music_file = ""
    project.save(update_fields=["output_file", "voiceover_file", "subtitle_file", "music_file", "updated_at"])
    if cleanup_ok:
        log_event("project.cleaned", "Project media files and folders were deleted.", project=project)
    else:
        log_event(
            "project.cleanup_pending",
            "Project upload succeeded, but one or more files are still locked and will be retried later.",
            level="error",
            project=project,
        )
    return cleanup_ok


def delete_project_record(project: VideoProject, reason: str) -> None:
    project_id = project.id
    topic = project.topic
    title = project.topic.title
    purge_project_media(project)
    log_event(
        "project.deleted",
        f"Project '{title}' was removed after {reason}.",
        payload={"project_id": project_id, "title": title, "reason": reason},
    )
    project.delete()
    if not topic.projects.exists():
        topic.delete()


def cleanup_completed_projects() -> int:
    cleaned = 0
    for project in list(VideoProject.objects.filter(status__in=[JobStatus.POSTED, JobStatus.FAILED])):
        has_posted_job = project.publish_jobs.filter(status=JobStatus.POSTED).exists()
        reason = "successful upload" if has_posted_job else f"status {project.status}"
        delete_project_record(project, reason=reason)
        cleaned += 1
    return cleaned


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
    return _publish_job(job, now=now)


def _publish_job(job: PublishJob, now=None) -> PublishJob | None:
    now = now or timezone.now()
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
        job.project.refresh_from_db()
        if job.project.status != JobStatus.READY or job.project.progress_percent < 100 or not job.project.output_file:
            raise RuntimeError("Upload blocked because the video did not finish generating successfully.")

        job.status = JobStatus.POSTING
        job.started_at = now
        job.save(update_fields=["status", "started_at", "updated_at"])
        log_event("publish.started", f"Uploading video to {job.channel.platform}.", project=job.project, publish_job=job)

        result = get_uploader(job.channel.platform).upload(job)
        set_project_progress(job.project, 95, "Upload finished, cleaning local files...")
        job.status = result.status
        job.remote_post_id = result.remote_post_id
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "remote_post_id", "finished_at", "updated_at"])
        log_event("publish.success", f"Uploaded to {job.channel.platform}.", project=job.project, publish_job=job)

        if not job.project.publish_jobs.exclude(status=JobStatus.POSTED).exists():
            job.project.status = JobStatus.POSTED
            job.project.status_message = "Uploaded to YouTube and deleted locally."
            job.project.progress_percent = 100
            job.project.save(update_fields=["status", "status_message", "progress_percent", "updated_at"])
            delete_project_record(job.project, reason="successful upload")
        return job
    except Exception as exc:
        return _schedule_retry(job, exc)


def generate_latest_project() -> VideoProject | None:
    project = VideoProject.objects.order_by("-created_at").first()
    if not project:
        return None
    if project.status in [JobStatus.POSTED, JobStatus.POSTING]:
        return project
    generate_project_media(project)
    return project


def publish_project(project: VideoProject) -> PublishJob | None:
    jobs = ensure_publish_jobs(project)
    job = (
        project.publish_jobs.select_related("channel")
        .filter(status__in=[JobStatus.QUEUED, JobStatus.FAILED, JobStatus.SKIPPED])
        .order_by("order_index", "created_at")
        .first()
    )
    if not job:
        if not jobs:
            project.status_message = "Upload blocked because YouTube is not fully configured."
            project.failure_reason = "No enabled upload platform is available."
            project.save(update_fields=["status_message", "failure_reason", "updated_at"])
            log_event("publish.blocked", project.failure_reason, level="error", project=project)
            return None
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

    set_project_progress(project, 100, "Video validated. Uploading to YouTube...")
    return _publish_job(job)


def _run_generation_task(project_id: int) -> None:
    project = VideoProject.objects.filter(id=project_id).first()
    if not project:
        return
    try:
        generate_project_media(project)
        state = get_automation_state()
        if state.is_enabled and state.auto_upload:
            publish_project(project)
    except Exception as exc:
        project.status = JobStatus.FAILED
        project.failure_reason = str(exc)
        project.status_message = str(exc)
        project.progress_percent = 100
        project.save(update_fields=["status", "failure_reason", "status_message", "progress_percent", "updated_at"])
        purge_project_media(project)
        log_event("project.render_failed", str(exc), level="error", project=project)


def start_generation_async(project: VideoProject) -> None:
    if project.status == JobStatus.GENERATING:
        return
    set_project_progress(project, 10, "Generation started...")
    thread = threading.Thread(target=_run_generation_task, args=(project.id,), daemon=True)
    thread.start()


def _run_upload_task(project_id: int) -> None:
    project = VideoProject.objects.filter(id=project_id).first()
    if not project:
        return
    try:
        publish_project(project)
    except Exception as exc:
        project.status = JobStatus.FAILED
        project.failure_reason = str(exc)
        project.status_message = str(exc)
        project.progress_percent = 100
        project.save(update_fields=["status", "failure_reason", "status_message", "progress_percent", "updated_at"])
        purge_project_media(project)
        log_event("project.upload_failed", str(exc), level="error", project=project)


def start_upload_async(project: VideoProject) -> None:
    if project.status == JobStatus.POSTING:
        return
    set_project_progress(project, 100, "Video validated. Upload started...")
    thread = threading.Thread(target=_run_upload_task, args=(project.id,), daemon=True)
    thread.start()


def process_due_work() -> dict:
    if not acquire_lock("pipeline"):
        return {"ok": True, "detail": "pipeline-locked"}

    try:
        state = get_automation_state()
        if not state.is_enabled:
            return {"ok": True, "detail": "automation-paused"}

        cleaned_projects = cleanup_completed_projects()
        project = create_daily_project_if_needed()
        job = publish_next_job()
        state.last_cycle_at = timezone.now()
        state.last_error = ""
        state.save(update_fields=["last_cycle_at", "last_error", "updated_at"])
        log_event(
            "automation.cycle_complete",
            "Automation cycle finished.",
            payload={
                "created_project_id": getattr(project, "id", None),
                "processed_job_id": getattr(job, "id", None),
                "cleaned_projects": cleaned_projects,
            },
        )
        return {
            "ok": True,
            "created_project_id": getattr(project, "id", None),
            "processed_job_id": getattr(job, "id", None),
            "cleaned_projects": cleaned_projects,
        }
    except Exception as exc:
        state = get_automation_state()
        state.last_error = str(exc)
        state.save(update_fields=["last_error", "updated_at"])
        log_event("automation.cycle_failed", str(exc), level="error")
        raise
    finally:
        release_lock("pipeline")
