from .utils import truncate_text
from studio.models import EventLog, PublishJob, VideoProject


def log_event(event_type: str, message: str, level: str = "info", project: VideoProject | None = None, publish_job: PublishJob | None = None, payload: dict | None = None) -> None:
    EventLog.objects.create(
        level=level,
        event_type=event_type,
        project=project,
        publish_job=publish_job,
        message=truncate_text(message, 5000),
        payload=payload or {},
    )
