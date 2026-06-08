from __future__ import annotations

from pathlib import Path
import time
from urllib.parse import urlparse

import requests
from django.conf import settings

from .utils import truncate_text


def _clean_env_value(value) -> str:
    return "".join(str(value or "").split()).strip()


def instagram_upload_configured() -> bool:
    return all(
        [
            _clean_env_value(getattr(settings, "INSTAGRAM_TOKEN", "")),
            _clean_env_value(getattr(settings, "INSTAGRAM_ACCOUNT_ID", "")),
        ]
    )


def _graph_api_base() -> str:
    version = str(getattr(settings, "INSTAGRAM_GRAPH_API_VERSION", "v24.0")).strip() or "v24.0"
    return f"https://graph.facebook.com/{version}"


def _build_preview_url(project) -> str:
    base_url = str(getattr(settings, "APP_BASE_URL", "")).strip().rstrip("/")
    if not base_url:
        raise RuntimeError("APP_BASE_URL is missing, so Instagram cannot fetch the rendered video.")

    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").strip().lower()
    if hostname in {"127.0.0.1", "localhost", "0.0.0.0"}:
        raise RuntimeError(
            "APP_BASE_URL points to a local-only address. Set it to your public site URL before Instagram uploads."
        )

    output_path = Path(project.output_file)
    if not project.output_file or not output_path.exists():
        raise RuntimeError("Rendered video file is missing, so Instagram upload cannot start.")
    return f"{base_url}/dashboard/preview/{project.id}/"


def build_instagram_caption(project) -> str:
    default_tags = ["darkbrainscroll", "reels", "viral", "shorts"]
    tags: list[str] = []
    for tag in [*project.topic.hashtags[:10], *[f"#{tag}" for tag in default_tags]]:
        normalized = tag.lstrip("#").strip()
        if normalized and normalized.lower() not in {item.lower() for item in tags}:
            tags.append(normalized)

    description = (project.topic.description or project.topic.script or "").strip()
    caption_parts = [
        truncate_text(project.topic.title.strip(), 120),
        "",
        truncate_text(description, 1600),
        "",
        " ".join(f"#{tag}" for tag in tags[:18]) if tags else "#reels #viral",
    ]
    return truncate_text("\n".join(part for part in caption_parts if part is not None), 2200)


def _graph_post(path: str, payload: dict) -> dict:
    response = requests.post(path, data=payload, timeout=getattr(settings, "INSTAGRAM_API_TIMEOUT_SECONDS", 120))
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Instagram returned a non-JSON response with status {response.status_code}.") from exc
    if response.ok:
        return data
    error = data.get("error") or {}
    message = error.get("message") or data or response.text
    raise RuntimeError(f"Instagram upload failed: {message}")


def _graph_get(path: str, params: dict) -> dict:
    response = requests.get(path, params=params, timeout=getattr(settings, "INSTAGRAM_API_TIMEOUT_SECONDS", 120))
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Instagram returned a non-JSON response with status {response.status_code}.") from exc
    if response.ok:
        return data
    error = data.get("error") or {}
    message = error.get("message") or data or response.text
    raise RuntimeError(f"Instagram upload failed: {message}")


def _wait_for_container_ready(container_id: str) -> None:
    timeout_seconds = max(30, int(getattr(settings, "INSTAGRAM_PUBLISH_TIMEOUT_SECONDS", 900)))
    poll_seconds = max(3, int(getattr(settings, "INSTAGRAM_STATUS_POLL_SECONDS", 10)))
    deadline = time.time() + timeout_seconds
    status_url = f"{_graph_api_base()}/{container_id}"
    params = {
        "fields": "status_code",
        "access_token": _clean_env_value(settings.INSTAGRAM_TOKEN),
    }

    while time.time() < deadline:
        data = _graph_get(status_url, params)
        status_code = str(data.get("status_code") or "").upper()
        if status_code == "FINISHED":
            return
        if status_code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram media processing failed with status {status_code}.")
        time.sleep(poll_seconds)

    raise RuntimeError("Instagram media processing timed out before the reel became publishable.")


def upload_instagram_reel(project) -> str:
    if not instagram_upload_configured():
        raise RuntimeError("Instagram Graph API credentials are missing.")

    access_token = _clean_env_value(getattr(settings, "INSTAGRAM_TOKEN", ""))
    account_id = _clean_env_value(getattr(settings, "INSTAGRAM_ACCOUNT_ID", ""))
    container_url = f"{_graph_api_base()}/{account_id}/media"
    publish_url = f"{_graph_api_base()}/{account_id}/media_publish"
    preview_url = _build_preview_url(project)

    create_payload = {
        "media_type": "REELS",
        "video_url": preview_url,
        "caption": build_instagram_caption(project),
        "share_to_feed": "true" if getattr(settings, "INSTAGRAM_SHARE_TO_FEED", True) else "false",
        "access_token": access_token,
    }
    create_response = _graph_post(container_url, create_payload)
    creation_id = str(create_response.get("id") or "").strip()
    if not creation_id:
        raise RuntimeError("Instagram did not return a media container ID.")

    _wait_for_container_ready(creation_id)

    publish_response = _graph_post(
        publish_url,
        {
            "creation_id": creation_id,
            "access_token": access_token,
        },
    )
    published_id = str(publish_response.get("id") or publish_response.get("post_id") or "").strip()
    if not published_id:
        raise RuntimeError("Instagram did not return a reel ID after publishing.")
    return published_id
