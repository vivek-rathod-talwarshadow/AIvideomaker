from __future__ import annotations

import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from django.conf import settings

from .utils import truncate_text


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _project_content_format(project) -> str:
    for note in project.topic.source_notes or []:
        if str(note).startswith("content-format:"):
            return str(note).split(":", 1)[1].strip().lower()
    return str(project.caption_style.get("content_format") or "shorts").strip().lower()


def _extract_http_error_message(exc: HttpError) -> str:
    try:
        payload = json.loads(exc.content.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return str(exc)

    error = payload.get("error", {})
    message = error.get("message")
    if message:
        return message
    errors = error.get("errors") or []
    if errors:
        reason = errors[0].get("reason") or errors[0].get("message")
        if reason:
            return str(reason)
    return str(exc)


def _is_daily_upload_limit_error(message: str) -> bool:
    normalized = message.lower()
    return any(
        marker in normalized
        for marker in [
            "daily upload limit reached",
            "uploadlimitexceeded",
            "dailylimitexceeded",
        ]
    )


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
    is_longform = _project_content_format(project) == "longform"
    default_tags = (
        ["darkcuriosity", "mystery", "documentary", "storytelling", "darkbrainscroll"]
        if is_longform
        else ["shorts", "viral", "trending", "storytime", "darkbrainscroll", "youtubeShorts"]
    )
    tags = []
    for tag in [*project.topic.hashtags[:10], *[f"#{tag}" for tag in default_tags]]:
        normalized = tag.lstrip("#").strip()
        if normalized and normalized.lower() not in {item.lower() for item in tags}:
            tags.append(normalized)

    title = (
        truncate_text(f"{project.topic.title} | {settings.CHANNEL_BRAND_NAME}", 95)
        if is_longform
        else truncate_text(f"{project.topic.title} | {settings.CHANNEL_BRAND_NAME} #Shorts", 95)
    )
    niche_descriptions = {
        "dark-curiosity": "dark curiosity, unexplained mysteries, and suspense-driven shorts",
        "glam": "scroll-stopping glam, dance, and creator-style shorts",
        "celebrity": "celebrity moments, glam reactions, and social buzz shorts",
        "reddit": "POV drama and story-driven shorts",
        "psychology": "social psychology and attraction-pattern shorts",
    }
    longform_niche_descriptions = {
        "dark-curiosity": "long-form dark curiosity stories, unexplained mysteries, and suspense-driven documentaries",
    }
    channel_blurb = (
        longform_niche_descriptions.get(project.niche, "long-form mystery storytelling videos")
        if is_longform
        else niche_descriptions.get(project.niche, "fast viral story-driven shorts")
    )
    description_lines = [
        f"{settings.CHANNEL_BRAND_NAME} brings you {channel_blurb}.",
        "",
        project.topic.description or project.topic.script,
        "",
        " ".join(f"#{tag}" for tag in tags[:12]) if tags else ("#darkcuriosity #mystery" if is_longform else "#shorts #viral"),
    ]

    return {
        "snippet": {
            "title": title,
            "description": truncate_text("\n".join(description_lines), 4900),
            "tags": tags[:15],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": settings.YOUTUBE_PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_youtube_video(project) -> str:
    service = build_youtube_service()
    request = service.videos().insert(
        part="snippet,status",
        body=build_youtube_metadata(project),
        media_body=MediaFileUpload(project.output_file, chunksize=-1, resumable=True),
    )
    response = None
    try:
        while response is None:
            _, response = request.next_chunk()
    except HttpError as exc:
        message = _extract_http_error_message(exc)
        if _is_daily_upload_limit_error(message):
            raise RuntimeError(
                "YouTube daily upload limit reached. Waiting until the next day before retrying."
            ) from exc
        raise RuntimeError(f"YouTube upload failed: {message}") from exc

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube upload completed without returning a video ID.")
    return video_id


def upload_youtube_short(project) -> str:
    return upload_youtube_video(project)
