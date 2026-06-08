from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from socket import gethostname
import threading

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from studio.enums import ContentNiche, JobStatus, PlatformType
from studio.models import AutomationState, ChannelProfile, EventLog, PublishJob, SchedulerLock, VideoProject, ViralTopic
from .logging_service import log_event
from .instagram import instagram_upload_configured
from .music import generate_background_music
from .renderer import render_slideshow_video
from .source_fetcher import fetch_scene_assets
from .subtitles import generate_basic_srt
from .topic_generator import (
    build_ai_topic,
    build_brainrot_video_topic,
    build_longform_topic,
    estimate_duration_seconds,
    estimate_longform_duration_seconds,
)
from .uploaders import get_uploader
from .utils import file_sha1, safe_rmtree, safe_unlink, stable_hash
from .voiceover import DEFAULT_VOICE_NAME, generate_voiceover, resolve_voice_name


AUTOMATION_NICHE_ORDER = (
    ContentNiche.DARK_CURIOSITY,
)


PROVIDER_BUDGET_ERROR_MARKERS = (
    "quota exceeded",
    "free usage limit reached",
    "service is now suspended until the next billing period",
    "upgrade your plan to restore your service",
    "billing details",
    "credit balance is too low",
    "insufficient credits",
    "rate limit exceeded for requests",
    "exceeded your current quota",
    "resource has been exhausted",
)

NON_RETRYABLE_UPLOAD_ERROR_MARKERS = (
    "invalid oauth access token",
    "cannot parse access token",
    "access token has expired",
    "oauthexception",
    "instagram username/password fallback is not configured",
    "bad password",
    "challenge_required",
    "two-factor",
)

TERMINAL_INSTAGRAM_AUTH_ERROR_MARKERS = (
    "invalid oauth access token",
    "cannot parse access token",
    "access token has expired",
    "session has expired",
    "permissions error",
    "unsupported post request",
    "application does not have the capability",
    "bad password",
    "challenge_required",
    "two-factor",
    "you can log in with your linked facebook account",
)


def _project_content_format(project: VideoProject) -> str:
    for note in project.topic.source_notes or []:
        if str(note).startswith("content-format:"):
            return str(note).split(":", 1)[1].strip().lower()
    return str(project.caption_style.get("content_format") or "shorts").strip().lower()


def _video_dimensions_for_format(content_format: str) -> tuple[int, int]:
    if content_format == "longform":
        width = max(640, int(getattr(settings, "LONGFORM_TARGET_WIDTH", 1920)))
        height = max(360, int(getattr(settings, "LONGFORM_TARGET_HEIGHT", 1080)))
        return width, height
    width = max(360, int(getattr(settings, "DEFAULT_VIDEO_WIDTH", 720)))
    height = max(640, int(getattr(settings, "DEFAULT_VIDEO_HEIGHT", 1280)))
    return width, height


def _project_render_mode(project: VideoProject) -> str:
    for note in project.topic.source_notes or []:
        if str(note).startswith("render-mode:"):
            return str(note).split(":", 1)[1].strip().lower()
    return str(project.caption_style.get("render_mode") or "").strip().lower()


def _project_duration_seconds(project: VideoProject) -> int:
    if _project_content_format(project) == "longform":
        return estimate_longform_duration_seconds(project.topic.script, project.topic.scene_plan)
    estimated = estimate_duration_seconds(project.topic.script, project.topic.scene_plan)
    if _project_render_mode(project) == "brainrot-video":
        return max(90, min(180, estimated + 36))
    return estimated


def _recent_automation_entries(limit: int = 100, *, content_format: str | None = None) -> list[dict]:
    entries: list[dict] = []
    logs = EventLog.objects.filter(event_type="project.created").order_by("-created_at")[:limit]
    for log in logs:
        payload = log.payload or {}
        if payload.get("automation") is False:
            continue
        logged_format = str(payload.get("content_format") or "shorts").strip().lower()
        if content_format and logged_format != content_format:
            continue
        title = str(payload.get("title") or "").strip()
        niche = str(payload.get("niche") or "").strip()
        if title or niche:
            entries.append({"title": title, "niche": niche})
    return entries


def _automation_projects_created_today(content_format: str = "shorts") -> int:
    today = timezone.localdate()
    count = 0
    for log in EventLog.objects.filter(
        event_type="project.created",
        created_at__date=today,
        payload__automation=True,
    ):
        logged_format = str((log.payload or {}).get("content_format") or "shorts").strip().lower()
        if logged_format == content_format:
            count += 1
    return count


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


def _project_content_signature(project: VideoProject) -> str:
    if project.content_signature:
        return project.content_signature
    normalized_script = " ".join((project.topic.script or "").lower().split())
    signature = stable_hash([project.niche, project.topic.title.strip().lower(), normalized_script])
    project.content_signature = signature
    project.save(update_fields=["content_signature", "updated_at"])
    return signature


def _ensure_output_fingerprint(project: VideoProject) -> str:
    if project.output_fingerprint:
        return project.output_fingerprint
    if not project.output_file or not Path(project.output_file).exists():
        return ""
    fingerprint = file_sha1(project.output_file)
    project.output_fingerprint = fingerprint
    project.save(update_fields=["output_fingerprint", "updated_at"])
    return fingerprint


def _mark_project_ready_if_output_exists(project: VideoProject) -> bool:
    output_path = Path(project.output_file) if project.output_file else None
    if not output_path or not output_path.exists():
        return False
    changed_fields: list[str] = ["updated_at"]
    if project.status != JobStatus.READY:
        project.status = JobStatus.READY
        changed_fields.append("status")
    if project.progress_percent < 100:
        project.progress_percent = 100
        changed_fields.append("progress_percent")
    ready_message = "Preview ready for upload."
    if project.status_message != ready_message:
        project.status_message = ready_message
        changed_fields.append("status_message")
    project.save(update_fields=changed_fields)
    return True


def _channel_upload_gap_minutes(channel: ChannelProfile) -> int:
    configured_gap = max(0, getattr(settings, "YOUTUBE_MIN_UPLOAD_GAP_MINUTES", 0))
    channel_gap = max(0, channel.cooldown_minutes)
    return max(configured_gap, channel_gap) if channel.platform == PlatformType.YOUTUBE else channel_gap


def _recent_channel_post(channel: ChannelProfile, now=None):
    now = now or timezone.now()
    gap_minutes = _channel_upload_gap_minutes(channel)
    if gap_minutes <= 0:
        return None
    return (
        EventLog.objects.filter(
            event_type="publish.success",
            payload__platform=channel.platform,
            created_at__gte=now - timedelta(minutes=gap_minutes),
        )
        .order_by("-created_at")
        .first()
    )


def _find_duplicate_uploaded_project(project: VideoProject):
    signature = _project_content_signature(project)
    duplicate_log = (
        EventLog.objects.filter(
            event_type__in=["publish.success", "project.deleted"],
            payload__content_signature=signature,
        )
        .exclude(project_id=project.id)
        .order_by("-created_at")
        .first()
    )
    if duplicate_log:
        return duplicate_log

    fingerprint = _ensure_output_fingerprint(project)
    if not fingerprint:
        return None
    return (
        EventLog.objects.filter(
            event_type__in=["publish.success", "project.deleted"],
            payload__output_fingerprint=fingerprint,
        )
        .exclude(project_id=project.id)
        .order_by("-created_at")
        .first()
    )


def _drop_duplicate_project(job: PublishJob, reason: str) -> PublishJob:
    project = job.project
    job.status = JobStatus.SKIPPED
    job.last_error = reason
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
    log_event("publish.duplicate_blocked", reason, level="error", project=project, publish_job=job)
    delete_project_record(project, reason="duplicate upload blocked")
    return job


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
            "default_voice_name": resolve_voice_name(getattr(settings, "EDGE_TTS_VOICE", DEFAULT_VOICE_NAME)),
            "brainrot_mode": True,
            "is_enabled": True,
            "auto_upload": True,
            "retry_failures": True,
            "last_started_at": timezone.now(),
        },
    )
    return state


def set_brainrot_mode(enabled: bool) -> AutomationState:
    state = get_automation_state()
    state.brainrot_mode = bool(enabled)
    state.save(update_fields=["brainrot_mode", "updated_at"])
    log_event(
        "automation.mode_changed",
        "Brainrot mode enabled." if enabled else "Brainrot mode disabled.",
        payload={"brainrot_mode": bool(enabled)},
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


def _next_local_day_start(now=None):
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    next_day = (local_now + timedelta(days=1)).date()
    naive_start = timezone.datetime.combine(next_day, timezone.datetime.min.time())
    return timezone.make_aware(naive_start, timezone.get_current_timezone())


def _youtube_limit_reached() -> bool:
    return False


def _should_retry_after_exception(exc: Exception) -> bool:
    normalized = str(exc).lower()
    if "youtube daily upload limit reached" in normalized:
        return False
    return not any(marker in normalized for marker in NON_RETRYABLE_UPLOAD_ERROR_MARKERS)


def _is_provider_budget_exhausted_error(exc: Exception) -> bool:
    normalized = str(exc).lower()
    return any(marker in normalized for marker in PROVIDER_BUDGET_ERROR_MARKERS)


def _pause_automation_for_budget_error(exc: Exception) -> None:
    state = get_automation_state()
    if not state.is_enabled:
        return
    state.is_enabled = False
    state.auto_upload = False
    state.last_paused_at = timezone.now()
    state.last_error = (
        "Automation paused to avoid burning provider or hosting free-tier limits. "
        f"Latest error: {exc}"
    )
    state.save(update_fields=["is_enabled", "auto_upload", "last_paused_at", "last_error", "updated_at"])
    log_event(
        "automation.paused_budget_guard",
        "Automation paused automatically after a quota, billing, or free-tier usage limit error.",
        level="error",
        payload={"error": str(exc)},
    )


def _defer_job(job: PublishJob, scheduled_for, reason: str, event_type: str = "publish.deferred") -> PublishJob:
    job.status = JobStatus.QUEUED
    job.last_error = reason
    job.finished_at = None
    job.scheduled_for = scheduled_for
    job.save(update_fields=["status", "last_error", "finished_at", "scheduled_for", "updated_at"])

    project = job.project
    project.status = JobStatus.QUEUED
    project.failure_reason = ""
    project.status_message = reason[:255]
    project.save(update_fields=["status", "failure_reason", "status_message", "updated_at"])

    log_event(event_type, reason, project=project, publish_job=job)
    return job


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

    should_retry = state.retry_failures and job.retry_count <= retry_limit and _should_retry_after_exception(exc)
    if should_retry:
        keep_existing_video = bool(project.output_file and Path(project.output_file).exists())
        if not keep_existing_video:
            purge_project_media(project)
        job.status = JobStatus.QUEUED
        job.finished_at = None
        job.scheduled_for = next_retry
        job.save(update_fields=["status", "retry_count", "last_error", "finished_at", "scheduled_for", "updated_at"])
        project.status = JobStatus.QUEUED
        if keep_existing_video:
            project.status_message = f"Retrying the same uploaded video in {settings.AUTOMATION_RETRY_DELAY_SECONDS} seconds."
        else:
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
        purge_project_media(project)
        job.status = JobStatus.FAILED
        job.save(update_fields=["status", "retry_count", "last_error", "finished_at", "updated_at"])
        log_event("publish.failed", str(exc), level="error", project=project, publish_job=job)
        delete_project_record(project, reason="final failure")
    return job


def _fail_pending_jobs_for_project(project: VideoProject, reason: str) -> int:
    pending_jobs = list(
        project.publish_jobs.filter(
            status__in=[JobStatus.QUEUED, JobStatus.GENERATING, JobStatus.READY, JobStatus.POSTING]
        )
    )
    if not pending_jobs:
        return 0

    now = timezone.now()
    updated_count = 0
    for job in pending_jobs:
        job.status = JobStatus.FAILED
        job.last_error = reason
        job.finished_at = now
        job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
        updated_count += 1
    return updated_count


def _project_has_incomplete_jobs(project: VideoProject) -> bool:
    return project.publish_jobs.exclude(status__in=[JobStatus.POSTED, JobStatus.SKIPPED]).exists()


def _skip_job(job: PublishJob, reason: str, *, event_type: str = "publish.skipped") -> PublishJob:
    job.status = JobStatus.SKIPPED
    job.last_error = reason
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
    log_event(event_type, reason, project=job.project, publish_job=job, level="error")

    if not _project_has_incomplete_jobs(job.project):
        job.project.status = JobStatus.POSTED
        job.project.status_message = "Uploaded to all available platforms. Skipped a terminal platform error."
        job.project.progress_percent = 100
        job.project.save(update_fields=["status", "status_message", "progress_percent", "updated_at"])
        delete_project_record(job.project, reason="successful upload with skipped terminal platform")
    else:
        _release_next_project_job(job.project, job.order_index)
    return job


def _release_next_project_job(project: VideoProject, completed_order_index: int, now=None) -> PublishJob | None:
    now = now or timezone.now()
    next_job = (
        project.publish_jobs.filter(
            status=JobStatus.QUEUED,
            order_index__gt=completed_order_index,
        )
        .order_by("order_index", "created_at")
        .first()
    )
    if not next_job:
        return None
    if next_job.scheduled_for > now:
        next_job.scheduled_for = now
        next_job.save(update_fields=["scheduled_for", "updated_at"])
    return next_job


def get_enabled_platforms() -> list[str]:
    platforms: list[str] = []
    if settings.ENABLE_YOUTUBE_UPLOAD and youtube_upload_configured():
        platforms.append(PlatformType.YOUTUBE)
    if settings.ENABLE_INSTAGRAM_UPLOAD and instagram_upload_configured():
        platforms.append(PlatformType.INSTAGRAM)
    if settings.ENABLE_PINTEREST_UPLOAD:
        platforms.append(PlatformType.PINTEREST)
    return platforms


def is_platform_enabled(platform: str) -> bool:
    return platform in get_enabled_platforms()


def _enabled_platforms_for_content_format(content_format: str) -> list[str]:
    if content_format == "longform":
        return [PlatformType.YOUTUBE] if PlatformType.YOUTUBE in get_enabled_platforms() else []
    return get_enabled_platforms()


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
    create_kwargs = {"platform": platform, "name": defaults[platform], "is_active": True}
    channel = ChannelProfile.objects.create(**create_kwargs)
    return channel


def _select_automation_niche() -> str:
    recent_niches = [
        entry["niche"]
        for entry in _recent_automation_entries(limit=len(AUTOMATION_NICHE_ORDER) * 4)
        if entry["niche"] in AUTOMATION_NICHE_ORDER
    ]
    for niche in AUTOMATION_NICHE_ORDER:
        if niche not in recent_niches:
            return niche
    latest_niche = recent_niches[0] if recent_niches else ""
    for niche in AUTOMATION_NICHE_ORDER:
        if niche != latest_niche:
            return niche
    return AUTOMATION_NICHE_ORDER[0]


def _title_used_recently(title: str, limit: int = 60, *, content_format: str | None = None) -> bool:
    normalized = title.strip().lower()
    if not normalized:
        return False
    for entry in _recent_automation_entries(limit=limit, content_format=content_format):
        if entry["title"].strip().lower() == normalized:
            return True
    return False


def _ordered_automation_niches() -> list[str]:
    preferred = _select_automation_niche()
    if preferred not in AUTOMATION_NICHE_ORDER:
        return list(AUTOMATION_NICHE_ORDER)
    start_index = AUTOMATION_NICHE_ORDER.index(preferred)
    return list(AUTOMATION_NICHE_ORDER[start_index:]) + list(AUTOMATION_NICHE_ORDER[:start_index])


def _build_unique_automation_topic() -> ViralTopic:
    for niche in _ordered_automation_niches():
        candidate = build_ai_topic(niche)
        if not _title_used_recently(candidate.title, limit=60, content_format="shorts"):
            return candidate
        candidate.delete()
    fallback_niche = _select_automation_niche()
    return build_ai_topic(fallback_niche)


def _build_unique_longform_topic() -> ViralTopic:
    for niche in _ordered_automation_niches():
        candidate = build_longform_topic(niche)
        if not _title_used_recently(candidate.title, limit=60, content_format="longform"):
            return candidate
        candidate.delete()
    fallback_niche = _select_automation_niche()
    return build_longform_topic(fallback_niche)


def _has_pending_project(content_format: str = "shorts") -> bool:
    pending_projects = VideoProject.objects.filter(
        status__in=[JobStatus.QUEUED, JobStatus.GENERATING, JobStatus.READY, JobStatus.POSTING]
    ).select_related("topic")
    return any(_project_content_format(project) == content_format for project in pending_projects)


def _longform_daily_target() -> int:
    minimum = max(1, int(getattr(settings, "LONGFORM_MIN_VIDEOS_PER_DAY", 2)))
    maximum = max(minimum, int(getattr(settings, "LONGFORM_MAX_VIDEOS_PER_DAY", 5)))
    today_key = timezone.localdate().isoformat()
    seed = int(stable_hash([today_key, "longform-daily-target"])[:8], 16)
    return minimum + (seed % (maximum - minimum + 1))


def _create_project_record(
    topic: ViralTopic,
    *,
    automation: bool,
    content_format: str,
    render_mode: str = "video-montage",
    status_message: str,
) -> VideoProject:
    target_width, target_height = _video_dimensions_for_format(content_format)
    default_voice_name = resolve_voice_name(get_automation_state().default_voice_name)
    duration_seconds = (
        estimate_longform_duration_seconds(topic.script, topic.scene_plan)
        if content_format == "longform"
        else estimate_duration_seconds(topic.script, topic.scene_plan)
    )
    project = VideoProject.objects.create(
        topic=topic,
        niche=topic.niche,
        voice_name=default_voice_name,
        status=JobStatus.QUEUED,
        aspect_ratio="16:9" if content_format == "longform" else "9:16",
        target_width=target_width,
        target_height=target_height,
        content_signature=stable_hash([topic.niche, topic.title.strip().lower(), " ".join(topic.script.lower().split())]),
        duration_seconds=duration_seconds,
        progress_percent=5,
        status_message=status_message,
        caption_style={
            "font_size": 42 if content_format == "longform" else 60,
            "stroke": 4,
            "highlight_color": "#F9D423",
            "text_color": "#FFFFFF",
            "position": "bottom-third",
            "brand_name": settings.CHANNEL_BRAND_NAME,
            "render_mode": render_mode,
            "content_format": content_format,
        },
    )
    fetch_scene_assets(project)
    enabled_platforms = _enabled_platforms_for_content_format(content_format)
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
    if automation:
        log_event(
            "automation.project_queued",
            f"{content_format.title()} project queued for automatic generation and upload.",
            project=project,
        )
    log_event(
        "project.created",
        f"{content_format.title()} project generated.",
        project=project,
        payload={
            "title": project.topic.title,
            "niche": project.niche,
            "automation": automation,
            "content_format": content_format,
            "mode": render_mode,
        },
    )
    return project


def create_daily_project_if_needed() -> VideoProject | None:
    created_today = _automation_projects_created_today("shorts")
    if created_today >= settings.MAX_VIDEOS_PER_DAY:
        return None
    state = get_automation_state()
    enabled_platforms = _enabled_platforms_for_content_format("shorts")
    if not enabled_platforms:
        log_event(
            "automation.skipped",
            "Automation did not create a project because no upload platform is fully configured.",
            level="error",
        )
        return None
    if _has_pending_project("shorts"):
        log_event(
            "automation.skipped",
            "Automation did not create a new project because an older video is still pending upload or retry.",
        )
        return None

    if state.brainrot_mode:
        project = create_brainrot_project(automation=True)
    else:
        topic = _build_unique_automation_topic()
        project = _create_project_record(
            topic,
            automation=True,
            content_format="shorts",
            render_mode="video-montage",
            status_message="Project created and waiting to generate.",
        )
    return project


def create_longform_project_if_needed() -> VideoProject | None:
    if not getattr(settings, "ENABLE_LONGFORM_AUTOMATION", True):
        return None
    created_today = _automation_projects_created_today("longform")
    if created_today >= _longform_daily_target():
        return None
    enabled_platforms = _enabled_platforms_for_content_format("longform")
    if not enabled_platforms:
        log_event(
            "automation.skipped",
            "Long-form automation did not create a project because YouTube is not fully configured.",
            level="error",
        )
        return None
    if _has_pending_project("longform"):
        log_event(
            "automation.skipped",
            "Long-form automation did not create a new project because an older long-form video is still pending.",
        )
        return None
    topic = _build_unique_longform_topic()
    return _create_project_record(
        topic,
        automation=True,
        content_format="longform",
        render_mode="video-montage",
        status_message="Long-form project created and waiting to generate.",
    )


def create_project(niche: str = "") -> VideoProject:
    niche = str(ContentNiche.DARK_CURIOSITY)
    topic = build_ai_topic(niche)
    return _create_project_record(
        topic,
        automation=False,
        content_format="shorts",
        render_mode="video-montage",
        status_message="Project created and waiting to generate.",
    )


def create_brainrot_project(automation: bool = False) -> VideoProject:
    topic = build_brainrot_video_topic()
    return _create_project_record(
        topic,
        automation=automation,
        content_format="shorts",
        render_mode="video-montage",
        status_message="Dark Curiosity project created and waiting to generate.",
    )


def create_longform_project(niche: str = "") -> VideoProject:
    niche = str(ContentNiche.DARK_CURIOSITY)
    topic = build_longform_topic(niche)
    return _create_project_record(
        topic,
        automation=False,
        content_format="longform",
        render_mode="video-montage",
        status_message="Long-form project created and waiting to generate.",
    )


def ensure_publish_jobs(project: VideoProject) -> list[PublishJob]:
    existing_jobs = list(project.publish_jobs.select_related("channel").order_by("order_index", "created_at"))
    enabled_platforms = _enabled_platforms_for_content_format(_project_content_format(project))
    existing_platforms = {job.channel.platform for job in existing_jobs}
    jobs = list(existing_jobs)
    created_jobs = False

    for order_index, platform in enumerate(enabled_platforms, start=1):
        if platform in existing_platforms:
            continue
        channel = get_or_create_default_channel(platform)
        jobs.append(
            PublishJob.objects.create(
                project=project,
                channel=channel,
                scheduled_for=timezone.now() + timedelta(minutes=(order_index - 1) * 20),
                order_index=order_index,
            )
        )
        created_jobs = True

    if created_jobs:
        jobs = list(project.publish_jobs.select_related("channel").order_by("order_index", "created_at"))
        log_event("publish.jobs_created", "Missing publish jobs were recreated automatically.", project=project)
    return jobs


def generate_project_media(project: VideoProject) -> None:
    project.status = JobStatus.GENERATING
    project.failure_reason = ""
    project.duration_seconds = _project_duration_seconds(project)
    project.save(update_fields=["status", "failure_reason", "duration_seconds", "updated_at"])
    set_project_progress(project, 15, "Preparing scene assets...")
    assets = list(project.assets.all())
    should_refresh_assets = (not assets) or any(not Path(asset.local_path).exists() for asset in assets if asset.local_path)
    if not should_refresh_assets:
        should_refresh_assets = any(bool((asset.metadata or {}).get("placeholder")) for asset in assets)
    if should_refresh_assets:
        fetch_scene_assets(project, replace_existing=bool(assets))
    render_mode = _project_render_mode(project)
    if render_mode == "brainrot-video":
        set_project_progress(project, 35, "Preparing background music...")
        generate_background_music(project)
        project.voiceover_file = ""
        project.subtitle_file = ""
        project.save(update_fields=["voiceover_file", "subtitle_file", "updated_at"])
        set_project_progress(project, 75, "Rendering brainrot montage...")
        log_event("project.render_started", "Rendering stock-footage montage with music.", project=project)
    else:
        set_project_progress(project, 35, "Generating voiceover...")
        log_event("project.voiceover_started", "Generating AI voiceover.", project=project)
        generate_voiceover(project)
        set_project_progress(project, 55, "Building subtitles...")
        generate_basic_srt(project)
        set_project_progress(project, 68, "Preparing background music...")
        generate_background_music(project)
        set_project_progress(project, 75, "Rendering video montage...")
        log_event("project.render_started", "Rendering stock-footage video with captions.", project=project)
    render_slideshow_video(project, progress_callback=lambda percent, message: set_project_progress(project, percent, message))
    if not _mark_project_ready_if_output_exists(project):
        raise RuntimeError("Render completed without creating a final video file.")
    try:
        _ensure_output_fingerprint(project)
    except Exception as exc:
        log_event("project.fingerprint_failed", str(exc), level="error", project=project)
    _mark_project_ready_if_output_exists(project)
    log_event("project.rendered", "Project assets and video generated.", project=project)


def purge_project_media(project: VideoProject) -> bool:
    cleanup_ok = True
    for asset in list(project.assets.all()):
        if asset.local_path:
            cleanup_ok = safe_unlink(asset.local_path) and cleanup_ok
    project.assets.all().delete()

    for path in [project.voiceover_file, project.subtitle_file, project.music_file, project.output_file]:
        if path:
            cleanup_ok = safe_unlink(path) and cleanup_ok

    project_root = Path(settings.MEDIA_ROOT) / "projects" / str(project.id)
    cleanup_ok = safe_rmtree(project_root) and cleanup_ok
    project.output_file = ""
    project.voiceover_file = ""
    project.subtitle_file = ""
    project.music_file = ""
    project.output_fingerprint = ""
    project.save(
        update_fields=["output_file", "voiceover_file", "subtitle_file", "music_file", "output_fingerprint", "updated_at"]
    )
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


def cleanup_orphaned_project_media() -> int:
    cleaned = 0
    projects_root = Path(settings.MEDIA_ROOT) / "projects"
    if not projects_root.exists():
        return cleaned

    for child in projects_root.iterdir():
        if not child.is_dir():
            continue
        try:
            project_id = int(child.name)
        except ValueError:
            if safe_rmtree(child):
                cleaned += 1
            continue
        if not VideoProject.objects.filter(id=project_id).exists() and safe_rmtree(child):
            cleaned += 1
    return cleaned


def delete_project_record(project: VideoProject, reason: str) -> None:
    project_id = project.id
    topic = project.topic
    title = project.topic.title
    content_signature = project.content_signature or _project_content_signature(project)
    output_fingerprint = project.output_fingerprint or _ensure_output_fingerprint(project)
    purge_project_media(project)
    log_event(
        "project.deleted",
        f"Project '{title}' was removed after {reason}.",
        payload={
            "project_id": project_id,
            "title": title,
            "reason": reason,
            "content_signature": content_signature,
            "output_fingerprint": output_fingerprint,
        },
    )
    project.delete()
    cleanup_orphaned_project_media()
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
    ).exclude(status__in=[JobStatus.POSTED, JobStatus.SKIPPED])
    if blockers.exists():
        return None

    try:
        if job.project.status not in [JobStatus.READY, JobStatus.POSTING, JobStatus.POSTED]:
            generate_project_media(job.project)
        job.project.refresh_from_db()
        if job.project.output_file and Path(job.project.output_file).exists():
            _mark_project_ready_if_output_exists(job.project)
            job.project.refresh_from_db()
        if job.project.status != JobStatus.READY or job.project.progress_percent < 100 or not job.project.output_file:
            raise RuntimeError("Upload blocked because the video did not finish generating successfully.")
        recent_post = _recent_channel_post(job.channel, now=now)
        if recent_post:
            next_slot = recent_post.created_at + timedelta(minutes=_channel_upload_gap_minutes(job.channel))
            return _defer_job(
                job,
                next_slot,
                f"Upload cooldown active. Waiting until {timezone.localtime(next_slot).strftime('%Y-%m-%d %H:%M:%S')} before the next {job.channel.get_platform_display()} upload.",
                event_type="publish.cooldown",
            )
        duplicate_project = _find_duplicate_uploaded_project(job.project)
        if duplicate_project:
            return _drop_duplicate_project(
                job,
                "Blocked duplicate upload because the same content or rendered video was already posted before.",
            )
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
        log_event(
            "publish.success",
            f"Uploaded to {job.channel.platform}.",
            project=job.project,
            publish_job=job,
            payload={
                "platform": job.channel.platform,
                "channel_id": job.channel_id,
                "project_id": job.project_id,
                "title": job.project.topic.title,
                "content_signature": _project_content_signature(job.project),
                "output_fingerprint": _ensure_output_fingerprint(job.project),
                "remote_post_id": job.remote_post_id,
            },
        )

        if not _project_has_incomplete_jobs(job.project):
            job.project.status = JobStatus.POSTED
            job.project.status_message = "Uploaded to all enabled platforms and deleted locally."
            job.project.progress_percent = 100
            job.project.save(update_fields=["status", "status_message", "progress_percent", "updated_at"])
            delete_project_record(job.project, reason="successful upload")
        else:
            _release_next_project_job(job.project, job.order_index, now=now)
            next_platform_job = (
                job.project.publish_jobs.filter(status=JobStatus.QUEUED).order_by("order_index", "created_at").first()
            )
            if next_platform_job:
                job.project.status = JobStatus.READY
                job.project.status_message = (
                    f"Uploaded to {job.channel.get_platform_display()}. "
                    f"Waiting for {next_platform_job.channel.get_platform_display()}."
                )[:255]
                job.project.progress_percent = 100
                job.project.save(update_fields=["status", "status_message", "progress_percent", "updated_at"])
        return job
    except Exception as exc:
        normalized_exc = str(exc).lower()
        if job.channel.platform == PlatformType.INSTAGRAM and any(
            marker in normalized_exc for marker in TERMINAL_INSTAGRAM_AUTH_ERROR_MARKERS
        ):
            return _skip_job(
                job,
                "Instagram upload skipped because the account token or login credentials are invalid. "
                "Fix the Instagram credentials before re-enabling Instagram uploads.",
                event_type="publish.skipped_terminal_instagram_auth",
            )
        if not _should_retry_after_exception(exc):
            return _defer_job(
                job,
                _next_local_day_start(now),
                str(exc),
                event_type="publish.rate_limited",
            )
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
            project.status_message = "Upload blocked because no enabled platform is fully configured."
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

    set_project_progress(project, 100, f"Video validated. Uploading to {job.channel.get_platform_display()}...")
    return _publish_job(job)


def _run_generation_task(project_id: int) -> None:
    project = VideoProject.objects.filter(id=project_id).first()
    if not project:
        return
    try:
        if _mark_project_ready_if_output_exists(project):
            return
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
        _fail_pending_jobs_for_project(project, str(exc))
        purge_project_media(project)
        log_event("project.render_failed", str(exc), level="error", project=project)


def start_generation_async(project: VideoProject) -> None:
    if project.status == JobStatus.GENERATING:
        return
    project.status = JobStatus.GENERATING
    project.failure_reason = ""
    project.status_message = "Generation started..."
    project.progress_percent = 10
    project.save(update_fields=["status", "failure_reason", "status_message", "progress_percent", "updated_at"])
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
    output_ready = bool(project.output_file and Path(project.output_file).exists())
    project.failure_reason = ""
    project.status_message = "Video validated. Upload started..."
    project.progress_percent = 100
    update_fields = ["failure_reason", "status_message", "progress_percent", "updated_at"]
    if project.status == JobStatus.READY and output_ready:
        project.status = JobStatus.POSTING
        update_fields.insert(0, "status")
    project.save(update_fields=update_fields)
    thread = threading.Thread(target=_run_upload_task, args=(project.id,), daemon=True)
    thread.start()


def dispatch_due_work() -> PublishJob | None:
    now = timezone.now()
    due_jobs = list(
        PublishJob.objects.select_related("project", "channel")
        .filter(status=JobStatus.QUEUED, scheduled_for__lte=now)
        .order_by("scheduled_for", "order_index", "created_at")
    )
    if not due_jobs:
        return None

    for job in due_jobs:
        if not is_platform_enabled(job.channel.platform):
            return _publish_job(job, now=now)

        blockers = PublishJob.objects.filter(
            project=job.project,
            order_index__lt=job.order_index,
        ).exclude(status__in=[JobStatus.POSTED, JobStatus.SKIPPED])
        if blockers.exists():
            continue

        project = job.project
        if project.status == JobStatus.GENERATING or project.status == JobStatus.POSTING:
            return job

        output_ready = bool(project.output_file and Path(project.output_file).exists())
        if project.status == JobStatus.READY and output_ready:
            start_upload_async(project)
            return job

        start_generation_async(project)
        return job
    return None


def process_due_work() -> dict:
    if not acquire_lock("pipeline"):
        return {"ok": True, "detail": "pipeline-locked"}

    try:
        state = get_automation_state()
        if not state.is_enabled:
            return {"ok": True, "detail": "automation-paused"}

        cleaned_orphans = cleanup_orphaned_project_media()
        cleaned_projects = cleanup_completed_projects()
        shorts_project = create_daily_project_if_needed()
        longform_project = create_longform_project_if_needed()
        job = dispatch_due_work()
        state.last_cycle_at = timezone.now()
        state.last_error = ""
        state.save(update_fields=["last_cycle_at", "last_error", "updated_at"])
        log_event(
            "automation.cycle_complete",
            "Automation cycle finished.",
            payload={
                "created_project_id": getattr(project, "id", None),
                "created_shorts_project_id": getattr(shorts_project, "id", None),
                "created_longform_project_id": getattr(longform_project, "id", None),
                "processed_job_id": getattr(job, "id", None),
                "cleaned_projects": cleaned_projects,
                "cleaned_orphan_media_dirs": cleaned_orphans,
            },
        )
        return {
            "ok": True,
            "created_project_id": getattr(shorts_project or longform_project, "id", None),
            "created_shorts_project_id": getattr(shorts_project, "id", None),
            "created_longform_project_id": getattr(longform_project, "id", None),
            "processed_job_id": getattr(job, "id", None),
            "cleaned_projects": cleaned_projects,
            "cleaned_orphan_media_dirs": cleaned_orphans,
        }
    except Exception as exc:
        state = get_automation_state()
        if _is_provider_budget_exhausted_error(exc):
            _pause_automation_for_budget_error(exc)
            state = get_automation_state()
        state.last_error = str(exc)
        state.save(update_fields=["last_error", "updated_at"])
        log_event("automation.cycle_failed", str(exc), level="error")
        raise
    finally:
        release_lock("pipeline")
