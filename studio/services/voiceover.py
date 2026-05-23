from __future__ import annotations

import asyncio
from pathlib import Path
import wave

from studio.models import VideoProject
from .utils import media_dir


VOICE_NAME = "en-US-AnaNeural"


async def _synthesize(text: str, output_path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=VOICE_NAME)
    await communicate.save(str(output_path))


def _write_silent_wav(output_path: Path, duration_seconds: int) -> None:
    frame_rate = 16000
    sample_width = 2
    channels = 1
    total_frames = max(duration_seconds, 1) * frame_rate
    silence = b"\x00" * sample_width * total_frames
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(silence)


def generate_voiceover(project: VideoProject) -> str:
    output_dir = media_dir("projects", str(project.id), "audio")
    output_path = output_dir / "voiceover.mp3"
    try:
        asyncio.run(_synthesize(project.topic.script, output_path))
    except ModuleNotFoundError:
        output_path = output_dir / "voiceover-fallback.wav"
        _write_silent_wav(output_path, project.duration_seconds)
    project.voiceover_file = str(output_path)
    project.save(update_fields=["voiceover_file", "updated_at"])
    return str(output_path)
