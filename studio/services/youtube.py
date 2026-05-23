from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from django.conf import settings

from .utils import truncate_text


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_youtube_credentials() -> Credentials:
    if not settings.YOUTUBE_CLIENT_ID or not settings.YOUTUBE_CLIENT_SECRET:
        raise RuntimeError("YouTube OAuth client ID/secret is missing.")
    if not settings.YOUTUBE_REFRESH_TOKEN:
        raise RuntimeError("YouTube refresh token is missing. Run generate_youtube_refresh_token first.")

    credentials = Credentials(
        token=None,
        refresh_token=settings.YOUTUBE_REFRESH_TOKEN,
        token_uri=YOUTUBE_TOKEN_URI,
        client_id=settings.YOUTUBE_CLIENT_ID,
        client_secret=settings.YOUTUBE_CLIENT_SECRET,
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )
    credentials.refresh(Request())
    return credentials


def build_youtube_service():
    credentials = build_youtube_credentials()
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def build_youtube_metadata(project) -> dict:
    title = truncate_text(f"{project.topic.title} #Shorts", 95)
    description_lines = [
        project.topic.description or project.topic.script,
        "",
        " ".join(project.topic.hashtags[:10]) if project.topic.hashtags else "#shorts",
    ]
    tags = [tag.lstrip("#") for tag in project.topic.hashtags[:10]]

    return {
        "snippet": {
            "title": title,
            "description": truncate_text("\n".join(description_lines), 4900),
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": settings.YOUTUBE_PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_youtube_short(project) -> str:
    service = build_youtube_service()
    request = service.videos().insert(
        part="snippet,status",
        body=build_youtube_metadata(project),
        media_body=MediaFileUpload(project.output_file, chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube upload completed without returning a video ID.")
    return video_id
