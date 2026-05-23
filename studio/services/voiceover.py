from __future__ import annotations

import asyncio
from pathlib import Path

from django.conf import settings
from studio.models import VideoProject
from .utils import media_dir


DEFAULT_VOICE_NAME = "en-US-AnaNeural"


async def _synthesize(text: str, output_path: Path) -> None:
    import edge_tts

    voice_name = getattr(settings, "EDGE_TTS_VOICE", DEFAULT_VOICE_NAME)
    communicate = edge_tts.Communicate(text=text, voice=voice_name)
    await communicate.save(str(output_path))


def generate_voiceover(project: VideoProject) -> str:
    output_dir = media_dir("projects", str(project.id), "audio")
    output_path = output_dir / "voiceover.mp3"
    try:
        asyncio.run(_synthesize(project.topic.script, output_path))
    except ModuleNotFoundError as exc:
        raise RuntimeError("edge-tts is not installed, so AI speech could not be generated.") from exc
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("AI speech generation failed: no voiceover file was produced.")
    project.voiceover_file = str(output_path)
    project.save(update_fields=["voiceover_file", "updated_at"])
    return str(output_path)
