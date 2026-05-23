from __future__ import annotations

from pathlib import Path
import textwrap

from studio.models import VideoProject
from .utils import media_dir


def _format_srt_timestamp(seconds: float) -> str:
    total_milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def _caption_chunks(text: str, max_words: int = 8) -> list[str]:
    words = text.split()
    if not words:
        return []
    if len(words) <= max_words:
        return [text.strip()]
    chunks = []
    for index in range(0, len(words), max_words):
        chunks.append(" ".join(words[index : index + max_words]))
    return chunks


def generate_basic_srt(project: VideoProject) -> str:
    output_dir = media_dir("projects", str(project.id), "subtitles")
    srt_path = output_dir / "captions.srt"

    scenes = [scene for scene in (project.topic.scene_plan or []) if (scene.get("text") or "").strip()]
    if not scenes:
        scenes = [{"text": line.strip(), "duration": 3} for line in project.topic.script.splitlines() if line.strip()]

    cursor = 0.0
    chunks = []
    subtitle_index = 1
    for scene in scenes:
        scene_text = (scene.get("text") or "").strip()
        scene_duration = max(2, int(scene.get("duration", 3) or 3))
        caption_parts = _caption_chunks(scene_text)
        if not caption_parts:
            continue
        part_duration = scene_duration / len(caption_parts)
        for part_index, caption in enumerate(caption_parts):
            start = cursor + (part_index * part_duration)
            end = cursor + ((part_index + 1) * part_duration)
            chunks.append(
                f"{subtitle_index}\n"
                f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n"
                f"{textwrap.fill(caption, width=28)}\n"
            )
            subtitle_index += 1
        cursor += scene_duration

    srt_path.write_text("\n".join(chunks), encoding="utf-8")
    project.subtitle_file = str(srt_path)
    project.save(update_fields=["subtitle_file", "updated_at"])
    return str(srt_path)
