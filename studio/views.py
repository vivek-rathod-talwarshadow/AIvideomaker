from pathlib import Path
import shutil

from django.conf import settings
from django.contrib import messages
from django.db import OperationalError, ProgrammingError
from django.db.models import Count
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .enums import JobStatus, PlatformType
from .models import EventLog, PublishJob, VideoProject
from .services.pipeline import get_automation_state


def _platform_status_cards() -> list[dict]:
    return [
        {
            "name": "YouTube Shorts",
            "platform": PlatformType.YOUTUBE,
            "enabled": settings.ENABLE_YOUTUBE_UPLOAD,
            "connected": all(
                [
                    getattr(settings, "YOUTUBE_CLIENT_ID", ""),
                    getattr(settings, "YOUTUBE_CLIENT_SECRET", ""),
                    getattr(settings, "YOUTUBE_REFRESH_TOKEN", ""),
                ]
            ),
            "note": "Primary live platform right now.",
        },
        {
            "name": "Instagram Reels",
            "platform": PlatformType.INSTAGRAM,
            "enabled": settings.ENABLE_INSTAGRAM_UPLOAD,
            "connected": all(
                [
                    getattr(settings, "INSTAGRAM_USERNAME", ""),
                    getattr(settings, "INSTAGRAM_PASSWORD", ""),
                ]
            ),
            "note": "Temporarily disabled until API details are added.",
        },
        {
            "name": "Pinterest Idea Pins",
            "platform": PlatformType.PINTEREST,
            "enabled": settings.ENABLE_PINTEREST_UPLOAD,
            "connected": all(
                [
                    getattr(settings, "PINTEREST_ACCESS_TOKEN", ""),
                    getattr(settings, "PINTEREST_BOARD_ID", ""),
                ]
            ),
            "note": "Temporarily disabled until API details are added.",
        },
    ]


def _provider_status_cards() -> list[dict]:
    ffmpeg_available = bool(
        shutil.which(getattr(settings, "FFMPEG_BINARY", "")) or Path(getattr(settings, "FFMPEG_BINARY", "")).exists()
    )
    return [
        {
            "name": "Gemini",
            "connected": bool(getattr(settings, "GEMINI_API_KEY", "")),
            "note": "Optional script generation provider.",
        },
        {
            "name": "Pexels",
            "connected": bool(getattr(settings, "PEXELS_API_KEY", "")),
            "note": "Primary stock asset source.",
        },
        {
            "name": "Pixabay",
            "connected": bool(getattr(settings, "PIXABAY_API_KEY", "")),
            "note": "Fallback asset source.",
        },
        {
            "name": "ffmpeg",
            "connected": ffmpeg_available,
            "note": "Required at deploy/runtime for rendering.",
        },
    ]


@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    context = {
        "platform_cards": _platform_status_cards(),
        "provider_cards": _provider_status_cards(),
        "recent_projects": [],
        "recent_jobs": [],
        "recent_logs": [],
        "automation_state": None,
        "stats": {
            "total_projects": 0,
            "queued_projects": 0,
            "ready_projects": 0,
            "posted_projects": 0,
            "failed_projects": 0,
            "disk_clean_projects": 0,
        },
        "setup_needed": False,
    }
    try:
        automation_state = get_automation_state()
        project_counts = {
            item["status"]: item["total"]
            for item in VideoProject.objects.values("status").annotate(total=Count("id"))
        }
        recent_projects = list(
            VideoProject.objects.select_related("topic")
            .prefetch_related("publish_jobs__channel")
            .order_by("-created_at")[:8]
        )
        recent_jobs = list(
            PublishJob.objects.select_related("project__topic", "channel")
            .order_by("-created_at")[:8]
        )
        recent_logs = list(EventLog.objects.select_related("project", "publish_job").order_by("-created_at")[:10])

        for project in recent_projects:
            project.video_exists = bool(project.output_file and Path(project.output_file).exists())
            project.asset_count = project.assets.count()
            project.is_previewable = project.video_exists and project.status in [JobStatus.READY, JobStatus.GENERATING, JobStatus.POSTING]

        latest_project = recent_projects[0] if recent_projects else None
        latest_preview_project = next((project for project in recent_projects if project.is_previewable), None)
        workflow_state = "Idle"
        workflow_tone = "ok"
        workflow_progress = 0
        if latest_project:
            state_map = {
                JobStatus.QUEUED: ("Queued", "warn"),
                JobStatus.GENERATING: ("Generating", "warn"),
                JobStatus.READY: ("Ready to upload", "ok"),
                JobStatus.POSTING: ("Uploading to YouTube", "warn"),
                JobStatus.POSTED: ("Uploaded and cleaned", "ok"),
                JobStatus.FAILED: ("Failed and cleaned", "off"),
                JobStatus.SKIPPED: ("Skipped", "off"),
            }
            workflow_state, workflow_tone = state_map.get(latest_project.status, ("Idle", "ok"))
            workflow_progress = latest_project.progress_percent

        context.update(
            {
                "recent_projects": recent_projects,
                "recent_jobs": recent_jobs,
                "recent_logs": recent_logs,
                "latest_project": latest_project,
                "latest_preview_project": latest_preview_project,
                "workflow_state": workflow_state,
                "workflow_tone": workflow_tone,
                "workflow_progress": workflow_progress,
                "stats": {
                    "total_projects": VideoProject.objects.count(),
                    "queued_projects": project_counts.get(JobStatus.QUEUED, 0),
                    "ready_projects": project_counts.get(JobStatus.READY, 0),
                    "posted_projects": project_counts.get(JobStatus.POSTED, 0),
                    "failed_projects": project_counts.get(JobStatus.FAILED, 0),
                    "disk_clean_projects": sum(1 for project in recent_projects if not project.video_exists),
                },
                "automation_state": automation_state,
            }
        )
    except (OperationalError, ProgrammingError):
        context["setup_needed"] = True

    return render(request, "studio/dashboard.html", context)


@require_GET
def healthcheck(request: HttpRequest) -> HttpResponse:
    return JsonResponse({"status": "ok", "service": "viralforge"})


@require_GET
def dashboard_status(request: HttpRequest) -> HttpResponse:
    try:
        project = VideoProject.objects.select_related("topic").order_by("-created_at").first()
        automation_state = get_automation_state()
        logs = list(EventLog.objects.select_related("project", "publish_job").order_by("-created_at")[:12])
    except (OperationalError, ProgrammingError):
        return JsonResponse({"has_project": False, "setup_needed": True})
    if not project:
        return JsonResponse(
            {
                "has_project": False,
                "automation_enabled": automation_state.is_enabled,
                "automation_last_cycle_at": automation_state.last_cycle_at.isoformat() if automation_state.last_cycle_at else "",
                "automation_last_error": automation_state.last_error,
                "recent_logs": [
                    {
                        "level": log.level,
                        "event_type": log.event_type,
                        "message": log.message,
                        "created_at": log.created_at.strftime("%b %d, %Y %H:%M"),
                    }
                    for log in logs
                ],
            }
        )

    preview_ready = bool(project.output_file and Path(project.output_file).exists())
    return JsonResponse(
        {
            "has_project": True,
            "project_id": project.id,
            "title": project.topic.title,
            "status": project.status,
            "status_message": project.status_message,
            "progress_percent": project.progress_percent,
            "failure_reason": project.failure_reason,
            "preview_ready": preview_ready,
            "preview_url": f"/dashboard/preview/{project.id}/" if preview_ready else "",
            "automation_enabled": automation_state.is_enabled,
            "automation_last_cycle_at": automation_state.last_cycle_at.isoformat() if automation_state.last_cycle_at else "",
            "automation_last_error": automation_state.last_error,
            "recent_logs": [
                {
                    "level": log.level,
                    "event_type": log.event_type,
                    "message": log.message,
                    "created_at": log.created_at.strftime("%b %d, %Y %H:%M"),
                }
                for log in logs
            ],
        }
    )


@require_POST
def run_automation_once(request: HttpRequest) -> HttpResponse:
    token = request.headers.get("X-Automation-Token", "")
    expected = getattr(settings, "AUTOMATION_WEBHOOK_TOKEN", None) or settings.SECRET_KEY
    if token != expected:
        return JsonResponse({"detail": "unauthorized"}, status=401)

    from .services.pipeline import process_due_work

    result = process_due_work()
    return JsonResponse(result)


@require_POST
def run_automation_now(request: HttpRequest) -> HttpResponse:
    from .services.pipeline import process_due_work

    try:
        result = process_due_work()
        messages.success(request, f"Automation run finished: {result}")
    except Exception as exc:
        messages.error(request, f"Automation run failed: {exc}")
    return redirect("dashboard")


@require_POST
def automation_start(request: HttpRequest) -> HttpResponse:
    from .services.pipeline import start_automation, process_due_work

    start_automation()
    try:
        result = process_due_work()
        messages.success(request, f"Automation started. Latest cycle: {result}")
    except Exception as exc:
        messages.error(request, f"Automation started, but the first cycle failed: {exc}")
    return redirect("dashboard")


@require_POST
def automation_pause(request: HttpRequest) -> HttpResponse:
    from .services.pipeline import pause_automation

    state = pause_automation()
    messages.success(request, "Automation paused. New uploads and generation cycles are on hold.")
    return redirect("dashboard")


@require_POST
def start_new_project(request: HttpRequest) -> HttpResponse:
    from .services.pipeline import create_project

    project = create_project()
    messages.success(request, f"Created project #{project.id}: {project.topic.title}")
    return redirect("dashboard")


@require_POST
def start_generate(request: HttpRequest) -> HttpResponse:
    from .services.pipeline import start_generation_async

    project = VideoProject.objects.order_by("-created_at").first()
    if not project:
        messages.warning(request, "No project found. Create one first.")
    else:
        start_generation_async(project)
        messages.success(request, f"Generation started for project #{project.id}.")
    return redirect("dashboard")


@require_POST
def start_upload(request: HttpRequest) -> HttpResponse:
    from .services.pipeline import start_upload_async

    project = VideoProject.objects.order_by("-created_at").first()
    if not project:
        messages.warning(request, "No project found. Create one first.")
        return redirect("dashboard")

    start_upload_async(project)
    messages.success(request, f"Upload started for project #{project.id}.")
    return redirect("dashboard")


@require_GET
def preview_video(request: HttpRequest, project_id: int) -> HttpResponse:
    project = VideoProject.objects.filter(id=project_id).first()
    if not project or not project.output_file:
        raise Http404("Preview not available.")
    path = Path(project.output_file)
    if not path.exists():
        raise Http404("Preview file not found.")
    return FileResponse(path.open("rb"), content_type="video/mp4")
