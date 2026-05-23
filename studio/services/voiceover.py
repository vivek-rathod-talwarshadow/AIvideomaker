from __future__ import annotations

import asyncio
from pathlib import Path
import time

from django.conf import settings
from studio.models import VideoProject
from .utils import media_dir


DEFAULT_VOICE_NAME = "en-US-AnaNeural"


async def _synthesize(text: str, output_path: Path) -> None:
    import edge_tts

    voice_name = getattr(settings, "EDGE_TTS_VOICE", DEFAULT_VOICE_NAME)
    communicate = edge_tts.Communicate(text=text, voice=voice_name)
    await communicate.save(str(output_path))


def _voiceover_attempts() -> int:
    return max(1, int(getattr(settings, "EDGE_TTS_MAX_RETRIES", 3)))


def _voiceover_retry_delay() -> float:
    return max(0.0, float(getattr(settings, "EDGE_TTS_RETRY_DELAY_SECONDS", 2)))


def _normalize_voiceover_error(exc: Exception) -> str:
    message = str(exc)
    if "Invalid response status" in message and "speech.platform.bing.com" in message:
        return (
            "Edge TTS rejected the websocket request with HTTP 403. "
            "This is usually a temporary upstream/network block, so the pipeline should retry automatically. "
            f"Original error: {message}"
        )
    return message


def generate_voiceover(project: VideoProject) -> str:
    output_dir = media_dir("projects", str(project.id), "audio")
    output_path = output_dir / "voiceover.mp3"
    last_error: Exception | None = None
    try:
        for attempt in range(1, _voiceover_attempts() + 1):
            try:
                if output_path.exists():
                    output_path.unlink()
                asyncio.run(_synthesize(project.topic.script, output_path))
                break
            except ModuleNotFoundError as exc:
                raise RuntimeError("edge-tts is not installed, so AI speech could not be generated.") from exc
            except Exception as exc:
                last_error = exc
                if attempt >= _voiceover_attempts():
                    raise RuntimeError(_normalize_voiceover_error(exc)) from exc
                time.sleep(_voiceover_retry_delay() * attempt)
    except ModuleNotFoundError as exc:
        raise RuntimeError("edge-tts is not installed, so AI speech could not be generated.") from exc
    if not output_path.exists() or output_path.stat().st_size == 0:
        if last_error is not None:
            raise RuntimeError(_normalize_voiceover_error(last_error)) from last_error
        raise RuntimeError("AI speech generation failed: no voiceover file was produced.")
    project.voiceover_file = str(output_path)
    project.save(update_fields=["voiceover_file", "updated_at"])
    return str(output_path)
