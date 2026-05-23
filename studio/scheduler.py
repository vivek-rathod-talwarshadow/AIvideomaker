from __future__ import annotations

import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)
try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ModuleNotFoundError:
    BackgroundScheduler = None

_scheduler: BackgroundScheduler | None = None


def boot_scheduler() -> None:
    global _scheduler

    if not settings.ENABLE_SCHEDULER:
        return
    if BackgroundScheduler is None:
        logger.warning("APScheduler is not installed; automation scheduler is disabled.")
        return
    if os.environ.get("RUN_MAIN") != "true" and settings.DEBUG:
        return
    if _scheduler is not None:
        return

    from .services.pipeline import process_due_work

    _scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    _scheduler.add_job(
        process_due_work,
        "interval",
        seconds=settings.SCHEDULER_POLL_SECONDS,
        max_instances=1,
        coalesce=True,
        id="process_due_work",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler booted with interval %s seconds", settings.SCHEDULER_POLL_SECONDS)
