from __future__ import annotations

from pathlib import Path
import subprocess
import shutil

from django.conf import settings

from studio.models import VideoProject
from .utils import media_dir


FFMPEG_ARGS = [
    "-y",
    "-r",
    "30",
    "-pix_fmt",
    "yuv420p",
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    "28",
    "-movflags",
    "+faststart",
    "-c:a",
    "aac",
    "-b:a",
    "128k",
]


def render_slideshow_video(project: VideoProject) -> str:
    output_dir = media_dir("projects", str(project.id), "output")
    output_path = output_dir / "final.mp4"

    ffmpeg_path = shutil.which(settings.FFMPEG_BINARY) or (
        settings.FFMPEG_BINARY if Path(settings.FFMPEG_BINARY).exists() else None
    )
    if not ffmpeg_path:
        raise RuntimeError(
            "ffmpeg is not installed or not available on PATH. Install ffmpeg or set FFMPEG_BINARY to its full path."
        )

    # Lightweight placeholder render path:
    # the real implementation should generate a concat input list and compose
    # image clips + subtitles + audio. For Render Free, keep video lengths short.
    command = [
        ffmpeg_path,
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={project.target_width}x{project.target_height}:d={project.duration_seconds}",
        "-i",
        project.voiceover_file,
        *FFMPEG_ARGS,
        "-shortest",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)

    project.output_file = str(output_path)
    project.status = "ready"
    project.save(update_fields=["output_file", "status", "updated_at"])
    return str(output_path)
