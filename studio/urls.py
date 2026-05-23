from django.urls import path

from .views import dashboard, healthcheck, preview_video, run_automation_now, run_automation_once, start_generate, start_new_project, start_upload

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("health/", healthcheck, name="healthcheck"),
    path("dashboard/run/", run_automation_now, name="run-automation-now"),
    path("dashboard/new-project/", start_new_project, name="start-new-project"),
    path("dashboard/generate/", start_generate, name="start-generate"),
    path("dashboard/upload/", start_upload, name="start-upload"),
    path("dashboard/preview/<int:project_id>/", preview_video, name="preview-video"),
    path("automation/run-once/", run_automation_once, name="run-automation-once"),
]
