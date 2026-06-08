from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from studio.enums import PlatformType
from studio.models import PublishJob


@dataclass
class UploadResult:
    remote_post_id: str
    status: str = "posted"


class BaseUploader:
    platform: str

    def upload(self, job: PublishJob) -> UploadResult:
        raise NotImplementedError


class YouTubeUploader(BaseUploader):
    platform = PlatformType.YOUTUBE

    def upload(self, job: PublishJob) -> UploadResult:
        video_path = Path(job.project.output_file)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        from .youtube import upload_youtube_short

        remote_post_id = upload_youtube_short(job.project)
        return UploadResult(remote_post_id=remote_post_id)


class InstagramUploader(BaseUploader):
    platform = PlatformType.INSTAGRAM

    def upload(self, job: PublishJob) -> UploadResult:
        video_path = Path(job.project.output_file)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        from .instagram import upload_instagram_reel

        remote_post_id = upload_instagram_reel(job.project)
        return UploadResult(remote_post_id=remote_post_id)


class PinterestUploader(BaseUploader):
    platform = PlatformType.PINTEREST

    def upload(self, job: PublishJob) -> UploadResult:
        raise RuntimeError("Pinterest upload is disabled for now.")


def get_uploader(platform: str) -> BaseUploader:
    if platform == PlatformType.INSTAGRAM and not settings.ENABLE_INSTAGRAM_UPLOAD:
        raise RuntimeError("Instagram upload is disabled in settings.")
    if platform == PlatformType.PINTEREST and not settings.ENABLE_PINTEREST_UPLOAD:
        raise RuntimeError("Pinterest upload is disabled in settings.")
    if platform == PlatformType.YOUTUBE and not settings.ENABLE_YOUTUBE_UPLOAD:
        raise RuntimeError("YouTube upload is disabled in settings.")

    mapping = {
        PlatformType.YOUTUBE: YouTubeUploader(),
        PlatformType.INSTAGRAM: InstagramUploader(),
        PlatformType.PINTEREST: PinterestUploader(),
    }
    return mapping[platform]
