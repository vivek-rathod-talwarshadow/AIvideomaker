from __future__ import annotations

import asyncio
from pathlib import Path
import time

from django.conf import settings
from studio.models import AutomationState, VideoProject
from .utils import media_dir


DEFAULT_VOICE_NAME = "en-US-ChristopherNeural"
VOICE_SAMPLE_TEXT = (
    "Tonight's mystery gets stranger with every clue. Stay close, because the final twist changes everything."
)
VOICE_OPTIONS = (
    {
        "value": "en-US-ChristopherNeural",
        "label": "Christopher",
        "description": "Deep, natural, authoritative male voice.",
    },
    {
        "value": "en-US-SteffanNeural",
        "label": "Steffan",
        "description": "Calm, grounded male voice with a serious tone.",
    },
    {
        "value": "en-US-EricNeural",
        "label": "Eric",
        "description": "Natural male voice with a rational delivery.",
    },
    {
        "value": "en-US-GuyNeural",
        "label": "Guy",
        "description": "Energetic male voice with a warmer edge.",
    },
)


def get_voice_options() -> list[dict]:
    return list(VOICE_OPTIONS)


def get_voice_map() -> dict[str, dict]:
    return {voice["value"]: voice for voice in VOICE_OPTIONS}


def resolve_voice_name(value: str | None) -> str:
    voice_name = (value or "").strip()
    return voice_name if voice_name in get_voice_map() else DEFAULT_VOICE_NAME


def get_project_voice_name(project: VideoProject) -> str:
    if project.voice_name:
        return resolve_voice_name(project.voice_name)
    default_voice = (
        AutomationState.objects.filter(key="global").values_list("default_voice_name", flat=True).first()
        or getattr(settings, "EDGE_TTS_VOICE", DEFAULT_VOICE_NAME)
    )
    return resolve_voice_name(default_voice)


async def _synthesize_with_voice(text: str, output_path: Path, voice_name: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=resolve_voice_name(voice_name))
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
    voice_name = get_project_voice_name(project)
    last_error: Exception | None = None
    try:
        for attempt in range(1, _voiceover_attempts() + 1):
            try:
                if output_path.exists():
                    output_path.unlink()
                asyncio.run(_synthesize_with_voice(project.topic.script, output_path, voice_name))
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
    project.voice_name = voice_name
    project.save(update_fields=["voiceover_file", "voice_name", "updated_at"])
    return str(output_path)


def generate_voice_sample(voice_name: str) -> Path:
    normalized_voice = resolve_voice_name(voice_name)
    output_dir = media_dir("voice_samples")
    output_path = output_dir / f"{normalized_voice}.mp3"
    if output_path.exists():
        return output_path
    asyncio.run(_synthesize_with_voice(VOICE_SAMPLE_TEXT, output_path, normalized_voice))
    return output_path
