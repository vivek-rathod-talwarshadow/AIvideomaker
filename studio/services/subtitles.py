from __future__ import annotations

from pathlib import Path

from studio.models import VideoProject
from .utils import media_dir


def generate_basic_srt(project: VideoProject) -> str:
    output_dir = media_dir("projects", str(project.id), "subtitles")
    srt_path = output_dir / "captions.srt"

    lines = [line.strip() for line in project.topic.script.splitlines() if line.strip()]
    cursor = 0
    chunks = []
    for index, line in enumerate(lines, start=1):
        start = cursor
        end = cursor + max(2, min(5, len(line.split()) // 2 + 2))
        chunks.append(
            f"{index}\n"
            f"00:00:{start:02d},000 --> 00:00:{end:02d},000\n"
            f"{line}\n"
        )
        cursor = end

    srt_path.write_text("\n".join(chunks), encoding="utf-8")
    project.subtitle_file = str(srt_path)
    project.save(update_fields=["subtitle_file", "updated_at"])
    return str(srt_path)
