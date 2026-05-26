from django.urls import path

from .views import (
    automation_pause,
    automation_start,
    dashboard,
    dashboard_status,
    favicon,
    healthcheck,
    preview_video,
    preview_voice_sample,
    run_automation_now,
    run_automation_once,
    set_default_voice,
    start_generate,
    start_new_project,
    start_upload,
)

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("favicon.ico", favicon, name="favicon"),
    path("health/", healthcheck, name="healthcheck"),
    path("dashboard/status/", dashboard_status, name="dashboard-status"),
    path("dashboard/automation/start/", automation_start, name="automation-start"),
    path("dashboard/automation/pause/", automation_pause, name="automation-pause"),
    path("dashboard/run/", run_automation_now, name="run-automation-now"),
    path("dashboard/new-project/", start_new_project, name="start-new-project"),
    path("dashboard/voice/", set_default_voice, name="set-default-voice"),
    path("dashboard/voice-sample/", preview_voice_sample, name="preview-voice-sample"),
    path("dashboard/generate/", start_generate, name="start-generate"),
    path("dashboard/upload/", start_upload, name="start-upload"),
    path("dashboard/preview/<int:project_id>/", preview_video, name="preview-video"),
    path("automation/run-once/", run_automation_once, name="run-automation-once"),
]
