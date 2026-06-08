from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from studio.enums import ContentNiche, JobStatus, PlatformType
from studio.models import ChannelProfile, PublishJob, VideoProject, ViralTopic
from studio.services.pipeline import _publish_job, _run_generation_task, dispatch_due_work


class PipelineQueueTests(TestCase):
    def _topic(self, title: str) -> ViralTopic:
        return ViralTopic.objects.create(
            niche=ContentNiche.DARK_CURIOSITY,
            title=title,
            hook="Hook",
            script="Script",
            scene_plan=[],
        )

    def _project(self, title: str, *, status: str = JobStatus.QUEUED) -> VideoProject:
        return VideoProject.objects.create(
            topic=self._topic(title),
            niche=ContentNiche.DARK_CURIOSITY,
            status=status,
        )

    def test_dispatch_due_work_skips_blocked_job_and_processes_next_runnable_job(self) -> None:
        now = timezone.now()
        youtube = ChannelProfile.objects.create(name="YT", platform=PlatformType.YOUTUBE, is_active=True)
        instagram = ChannelProfile.objects.create(name="IG", platform=PlatformType.INSTAGRAM, is_active=True)

        blocked_project = self._project("Blocked")
        PublishJob.objects.create(
            project=blocked_project,
            channel=youtube,
            status=JobStatus.QUEUED,
            order_index=1,
            scheduled_for=now + timedelta(minutes=10),
        )
        blocked_instagram_job = PublishJob.objects.create(
            project=blocked_project,
            channel=instagram,
            status=JobStatus.QUEUED,
            order_index=2,
            scheduled_for=now - timedelta(minutes=1),
        )

        runnable_project = self._project("Runnable")
        runnable_job = PublishJob.objects.create(
            project=runnable_project,
            channel=youtube,
            status=JobStatus.QUEUED,
            order_index=1,
            scheduled_for=now - timedelta(minutes=1),
        )

        with patch("studio.services.pipeline.start_generation_async") as start_generation_async:
            result = dispatch_due_work()

        self.assertEqual(result.id, runnable_job.id)
        start_generation_async.assert_called_once_with(runnable_project)
        blocked_instagram_job.refresh_from_db()
        self.assertEqual(blocked_instagram_job.status, JobStatus.QUEUED)

    def test_generation_failure_marks_pending_jobs_failed(self) -> None:
        project = self._project("Broken render")
        publish_job = PublishJob.objects.create(
            project=project,
            channel=ChannelProfile.objects.create(name="YT", platform=PlatformType.YOUTUBE, is_active=True),
            status=JobStatus.QUEUED,
            order_index=1,
            scheduled_for=timezone.now(),
        )

        with patch("studio.services.pipeline.generate_project_media", side_effect=RuntimeError("render exploded")):
            _run_generation_task(project.id)

        project.refresh_from_db()
        publish_job.refresh_from_db()
        self.assertEqual(project.status, JobStatus.FAILED)
        self.assertEqual(publish_job.status, JobStatus.FAILED)
        self.assertEqual(publish_job.last_error, "render exploded")

    def test_successful_upload_releases_next_platform_immediately(self) -> None:
        now = timezone.now()
        project = self._project("Sequential upload", status=JobStatus.READY)
        project.output_file = __file__
        project.progress_percent = 100
        project.save(update_fields=["output_file", "progress_percent", "updated_at"])

        youtube = ChannelProfile.objects.create(name="YT", platform=PlatformType.YOUTUBE, is_active=True)
        instagram = ChannelProfile.objects.create(name="IG", platform=PlatformType.INSTAGRAM, is_active=True)
        youtube_job = PublishJob.objects.create(
            project=project,
            channel=youtube,
            status=JobStatus.QUEUED,
            order_index=1,
            scheduled_for=now - timedelta(minutes=1),
        )
        instagram_job = PublishJob.objects.create(
            project=project,
            channel=instagram,
            status=JobStatus.QUEUED,
            order_index=2,
            scheduled_for=now + timedelta(minutes=19),
        )

        with patch("studio.services.pipeline.get_uploader") as get_uploader:
            uploader = get_uploader.return_value
            uploader.upload.return_value.status = JobStatus.POSTED
            uploader.upload.return_value.remote_post_id = "yt-123"
            _publish_job(youtube_job, now=now)

        instagram_job.refresh_from_db()
        project.refresh_from_db()
        self.assertLessEqual(instagram_job.scheduled_for, now)
        self.assertEqual(project.status, JobStatus.READY)
        self.assertIn("Waiting for Instagram Reels", project.status_message)
