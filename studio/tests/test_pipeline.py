from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from studio.enums import ContentNiche, JobStatus, PlatformType
from studio.models import AutomationState, ChannelProfile, PublishJob, VideoProject, ViralTopic
from studio.services.pipeline import (
    _publish_job,
    _run_generation_task,
    create_longform_project_if_needed,
    create_projects_for_niches,
    default_automation_niches,
    dispatch_due_work,
    get_automation_state,
    normalize_selected_niches,
    process_due_work,
    selected_automation_niches,
    set_selected_niches,
)
from studio.services.instagram import instagram_upload_configured, upload_instagram_reel
from studio.services.topic_generator import _validate_topic_payload
from studio.services.youtube import build_youtube_metadata


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

    @override_settings(
        ENABLE_YOUTUBE_UPLOAD=True,
        ENABLE_INSTAGRAM_UPLOAD=False,
        ENABLE_PINTEREST_UPLOAD=False,
        YOUTUBE_CLIENT_ID="client",
        YOUTUBE_CLIENT_SECRET="secret",
        YOUTUBE_REFRESH_TOKEN="refresh",
        ENABLE_LONGFORM_AUTOMATION=True,
        LONGFORM_MIN_VIDEOS_PER_DAY=2,
        LONGFORM_MAX_VIDEOS_PER_DAY=2,
        LONGFORM_TARGET_WIDTH=1920,
        LONGFORM_TARGET_HEIGHT=1080,
    )
    def test_longform_automation_creates_youtube_only_landscape_project(self) -> None:
        topic = ViralTopic.objects.create(
            niche=ContentNiche.DARK_CURIOSITY,
            title="The Cave Map Hidden Inside a Cold War Radio",
            hook="A forgotten radio diagram pointed to a sealed cave.",
            script="Intro\nBeat one\nBeat two\nBeat three\nOutro",
            scene_plan=[
                {"text": "Intro", "duration": 12, "visual_hint": "sealed cave entrance"},
                {"text": "Beat one", "duration": 14, "visual_hint": "cold war radio room"},
                {"text": "Beat two", "duration": 16, "visual_hint": "underground tunnel"},
                {"text": "Beat three", "duration": 18, "visual_hint": "mystery document"},
                {"text": "Outro", "duration": 12, "visual_hint": "dark cave map"},
            ],
            source_notes=["content-format:longform", "render-mode:video-montage"],
        )

        with patch("studio.services.pipeline.build_longform_topic", return_value=topic), patch(
            "studio.services.pipeline.fetch_scene_assets"
        ):
            project = create_longform_project_if_needed()

        self.assertIsNotNone(project)
        assert project is not None
        self.assertEqual(project.aspect_ratio, "16:9")
        self.assertEqual(project.target_width, 1920)
        self.assertEqual(project.target_height, 1080)
        self.assertEqual(project.publish_jobs.count(), 1)
        self.assertEqual(project.publish_jobs.first().channel.platform, PlatformType.YOUTUBE)

    def test_build_youtube_metadata_for_longform_omits_shorts_branding(self) -> None:
        topic = ViralTopic.objects.create(
            niche=ContentNiche.DARK_CURIOSITY,
            title="The Forest Recording That Should Not Exist",
            hook="A single audio tape changed the entire case.",
            script="Long-form mystery script",
            scene_plan=[],
            description="Long-form mystery description",
            hashtags=["#darkcuriosity", "#mystery"],
            source_notes=["content-format:longform"],
        )
        project = VideoProject.objects.create(
            topic=topic,
            niche=ContentNiche.DARK_CURIOSITY,
            caption_style={"content_format": "longform"},
        )

        metadata = build_youtube_metadata(project)

        self.assertNotIn("#Shorts", metadata["snippet"]["title"])
        self.assertNotIn("youtubeShorts", metadata["snippet"]["tags"])
        self.assertIn("mystery", " ".join(metadata["snippet"]["tags"]).lower())

    def test_dark_curiosity_category_is_normalized_instead_of_failing(self) -> None:
        payload = {
            "topics": [
                {
                    "category": "Unexplained Mystery",
                    "topic_formula": "mystery + danger + real event",
                    "title": "The Cave Radio That Should Not Exist",
                    "intro": "A dead radio led explorers underground.",
                    "bullets": ["Beat one", "Beat two", "Beat three", "Beat four", "Beat five", "Beat six"],
                    "cta": "No one knows who left it there.",
                    "hashtags": ["#darkcuriosity"],
                    "asset_packs": ["abandoned places"],
                    "visuals": ["cave entrance", "radio room", "tunnel", "map", "signal", "artifact", "dark cave", "mystery ending"],
                    "pixabay_keywords": [
                        "mystery", "cave", "radio", "tunnel", "artifact", "signal",
                        "underground", "dark", "ancient", "ruins", "map", "explorer",
                    ],
                    "viral_scores": {"curiosity": 9, "shock": 8, "retention": 8, "shareability": 8},
                }
            ]
        }

        normalized = _validate_topic_payload(payload, ContentNiche.DARK_CURIOSITY, "openai", "test-model")

        self.assertEqual(normalized["category"], "Unexplained Mysteries")

    @override_settings(
        INSTAGRAM_TOKEN="bad-token",
        INSTAGRAM_ACCOUNT_ID="17841427063072741",
        INSTAGRAM_USERNAME="dark_brain_scroll",
        INSTAGRAM_PASSWORD="bad-password",
        ENABLE_INSTAGRAM_PRIVATE_FALLBACK=False,
    )
    def test_instagram_private_fallback_disabled_by_default(self) -> None:
        self.assertTrue(instagram_upload_configured())

        topic = self._topic("IG Graph Only")
        project = VideoProject.objects.create(topic=topic, niche=ContentNiche.DARK_CURIOSITY, output_file=__file__)

        with patch("studio.services.instagram._upload_instagram_reel_via_graph_api", side_effect=RuntimeError("Instagram upload failed: Invalid OAuth access token - Cannot parse access token")), patch(
            "studio.services.instagram._upload_instagram_reel_via_private_api"
        ) as private_upload:
            with self.assertRaises(RuntimeError):
                upload_instagram_reel(project)

        private_upload.assert_not_called()

    def test_instagram_terminal_auth_error_skips_job(self) -> None:
        now = timezone.now()
        project = self._project("Instagram auth failure", status=JobStatus.READY)
        project.output_file = __file__
        project.progress_percent = 100
        project.save(update_fields=["output_file", "progress_percent", "updated_at"])

        instagram = ChannelProfile.objects.create(name="IG", platform=PlatformType.INSTAGRAM, is_active=True)
        instagram_job = PublishJob.objects.create(
            project=project,
            channel=instagram,
            status=JobStatus.QUEUED,
            order_index=1,
            scheduled_for=now - timedelta(minutes=1),
        )

        with patch("studio.services.pipeline.get_uploader") as get_uploader, patch(
            "studio.services.pipeline.delete_project_record"
        ) as delete_project_record:
            uploader = get_uploader.return_value
            uploader.upload.side_effect = RuntimeError("Instagram upload failed: Invalid OAuth access token - Cannot parse access token")
            _publish_job(instagram_job, now=now)

        instagram_job.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(instagram_job.status, JobStatus.SKIPPED)
        self.assertEqual(project.status, JobStatus.POSTED)
        delete_project_record.assert_called_once()

    def test_process_due_work_uses_short_and_longform_project_ids_without_name_error(self) -> None:
        with patch("studio.services.pipeline.acquire_lock", return_value=True), patch(
            "studio.services.pipeline.release_lock"
        ), patch("studio.services.pipeline.cleanup_orphaned_project_media", return_value=0), patch(
            "studio.services.pipeline.cleanup_completed_projects", return_value=0
        ), patch(
            "studio.services.pipeline.dispatch_due_work", return_value=None
        ), patch(
            "studio.services.pipeline.create_daily_project_if_needed", return_value=self._project("Shorts project")
        ) as create_short, patch(
            "studio.services.pipeline.create_longform_project_if_needed", return_value=self._project("Longform project")
        ) as create_long:
            result = process_due_work()

        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["created_project_id"])
        self.assertIsNotNone(result["created_shorts_project_id"])
        self.assertIsNotNone(result["created_longform_project_id"])
        create_short.assert_called_once()
        create_long.assert_called_once()

    def test_selected_niches_are_saved_and_disable_brainrot_for_multi_niche_mode(self) -> None:
        state = set_selected_niches([ContentNiche.ANIMALS, ContentNiche.CELEBRITY, "invalid-choice", ContentNiche.ANIMALS])

        self.assertEqual(selected_automation_niches(state), [ContentNiche.ANIMALS, ContentNiche.CELEBRITY])
        self.assertFalse(state.brainrot_mode)
        self.assertEqual(normalize_selected_niches(state.selected_niches), [ContentNiche.ANIMALS, ContentNiche.CELEBRITY])

    def test_selected_niches_fall_back_to_multi_niche_defaults(self) -> None:
        state = set_selected_niches([])

        self.assertEqual(selected_automation_niches(state), default_automation_niches())
        self.assertFalse(state.brainrot_mode)

    def test_default_niches_include_every_visible_dashboard_niche(self) -> None:
        expected = [choice.value for choice in ContentNiche if choice != ContentNiche.DARK_CURIOSITY]

        self.assertEqual(default_automation_niches(), expected)

    def test_legacy_three_niche_default_is_upgraded_to_all_visible_niches(self) -> None:
        AutomationState.objects.create(
            key="global",
            selected_niches=[ContentNiche.ANIMALS, ContentNiche.CELEBRITY, ContentNiche.PSYCHOLOGY]
        )

        refreshed = get_automation_state()

        self.assertEqual(refreshed.selected_niches, default_automation_niches())

    def test_create_projects_for_niches_creates_one_project_per_selected_niche(self) -> None:
        animal_topic = ViralTopic.objects.create(
            niche=ContentNiche.ANIMALS,
            title="Animal Topic",
            hook="Hook",
            script="Intro\nBody\nOutro",
            scene_plan=[],
        )
        car_topic = ViralTopic.objects.create(
            niche=ContentNiche.CARS,
            title="Car Topic",
            hook="Hook",
            script="Intro\nBody\nOutro",
            scene_plan=[],
        )

        with patch("studio.services.pipeline.build_ai_topic", side_effect=[animal_topic, car_topic]), patch(
            "studio.services.pipeline.fetch_scene_assets"
        ):
            projects = create_projects_for_niches([ContentNiche.ANIMALS, ContentNiche.CARS])

        self.assertEqual(len(projects), 2)
        self.assertEqual([project.niche for project in projects], [ContentNiche.ANIMALS, ContentNiche.CARS])
