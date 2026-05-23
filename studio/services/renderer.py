from __future__ import annotations

from math import ceil
from pathlib import Path
import shutil
import subprocess

from django.conf import settings

from studio.models import VideoProject
from .utils import media_dir


VIDEO_ONLY_ARGS = [
    "-y",
    "-pix_fmt",
    "yuv420p",
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    "24",
    "-movflags",
    "+faststart",
]

FINAL_RENDER_ARGS = [
    *VIDEO_ONLY_ARGS,
    "-c:a",
    "aac",
    "-b:a",
    "192k",
]


def _resolve_binary(name: str) -> str | None:
    if name == "ffprobe":
        configured_ffmpeg = getattr(settings, "FFMPEG_BINARY", "ffmpeg")
        ffmpeg_path = shutil.which(configured_ffmpeg) or (
            configured_ffmpeg if Path(configured_ffmpeg).exists() else None
        )
        if ffmpeg_path:
            sibling = Path(ffmpeg_path).with_name("ffprobe.exe" if Path(ffmpeg_path).suffix.lower() == ".exe" else "ffprobe")
            if sibling.exists():
                return str(sibling)
    configured = getattr(settings, "FFMPEG_BINARY", "ffmpeg") if name == "ffmpeg" else name
    return shutil.which(configured) or (configured if Path(configured).exists() else None)


def _ffprobe_duration(path: str) -> float:
    ffprobe_path = _resolve_binary("ffprobe")
    if not ffprobe_path:
        return 0.0
    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _pick_font_file() -> str:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate.replace("\\", "/")
    return "Arial"


def _drawtext_font_arg() -> str:
    font_value = _pick_font_file()
    if "/" in font_value or ":" in font_value:
        return f"fontfile='{_escape_filter_text(font_value)}':"
    return f"font='{_escape_filter_text(font_value)}':"


def _escape_filter_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace("%", r"\%")
        .replace("\n", r"\n")
    )


def _escape_subtitle_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", r"\:")


def _scene_durations(project: VideoProject, scene_count: int) -> list[int]:
    if scene_count <= 0:
        return []
    audio_duration = _ffprobe_duration(project.voiceover_file)
    total_duration = max(project.duration_seconds, ceil(audio_duration))
    scene_plan = list(project.topic.scene_plan or [])
    weights = [max(1, int(scene.get("duration", 0) or 0)) for scene in scene_plan[:scene_count]]
    while len(weights) < scene_count:
        weights.append(1)
    total_weight = sum(weights) or scene_count
    durations = [max(3, round(total_duration * weight / total_weight)) for weight in weights]
    difference = total_duration - sum(durations)
    index = 0
    while difference != 0 and durations:
        target = index % len(durations)
        if difference > 0:
            durations[target] += 1
            difference -= 1
        elif durations[target] > 3:
            durations[target] -= 1
            difference += 1
        index += 1
        if index > len(durations) * 10:
            break
    return durations


def _render_scene_clip(
    project: VideoProject,
    ffmpeg_path: str,
    asset,
    clip_path: Path,
    duration: int,
) -> None:
    font_arg = _drawtext_font_arg()
    brand_name = _escape_filter_text(project.caption_style.get("brand_name") or getattr(settings, "CHANNEL_BRAND_NAME", "DarkBrainScroll"))

    vf_parts = [
        f"scale={project.target_width}:{project.target_height}:force_original_aspect_ratio=increase",
        f"crop={project.target_width}:{project.target_height}",
        (
            "zoompan="
            f"z='min(zoom+0.0009,1.18)':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={duration * 30}:"
            f"s={project.target_width}x{project.target_height}:fps=30"
        ),
        "format=yuv420p",
        "drawbox=x=52:y=h-180:w=976:h=86:color=black@0.28:t=fill",
        (
            "drawtext="
            f"{font_arg}"
            f"text='{brand_name}':"
            "fontcolor=white@0.9:fontsize=34:"
            "x=74:y=h-126"
        ),
    ]

    command = [
        ffmpeg_path,
        "-y",
        "-loop",
        "1",
        "-i",
        asset.local_path,
        "-t",
        str(duration),
        "-an",
        "-vf",
        ",".join(vf_parts),
        "-r",
        "30",
        *VIDEO_ONLY_ARGS,
        str(clip_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        fallback_command = [
            ffmpeg_path,
            "-y",
            "-loop",
            "1",
            "-i",
            asset.local_path,
            "-t",
            str(duration),
            "-an",
            "-vf",
            ",".join(
                [
                    f"scale={project.target_width}:{project.target_height}:force_original_aspect_ratio=increase",
                    f"crop={project.target_width}:{project.target_height}",
                    "format=yuv420p",
                ]
            ),
            "-r",
            "30",
            *VIDEO_ONLY_ARGS,
            str(clip_path),
        ]
        try:
            subprocess.run(fallback_command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise RuntimeError(f"ffmpeg scene render failed for {asset.local_path}: {stderr or exc}") from exc


def render_slideshow_video(project: VideoProject) -> str:
    output_dir = media_dir("projects", str(project.id), "output")
    clips_dir = media_dir("projects", str(project.id), "output", "clips")
    output_path = output_dir / "final.mp4"
    assembled_path = output_dir / "assembled.mp4"
    concat_manifest = output_dir / "clips.txt"

    ffmpeg_path = _resolve_binary("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError(
            "ffmpeg is not installed or not available on PATH. Install ffmpeg or set FFMPEG_BINARY to its full path."
        )

    assets = list(project.assets.filter(asset_type="image").order_by("sort_order"))
    if not assets:
        raise RuntimeError("No image assets found for rendering.")
    if not project.voiceover_file:
        raise RuntimeError("Voiceover file is missing.")

    durations = _scene_durations(project, len(assets))
    clip_paths: list[Path] = []
    for index, (asset, duration) in enumerate(zip(assets, durations), start=1):
        clip_path = clips_dir / f"scene-{index:02d}.mp4"
        _render_scene_clip(project, ffmpeg_path, asset, clip_path, duration)
        clip_paths.append(clip_path)

    concat_manifest.write_text(
        "\n".join(f"file '{clip_path.resolve().as_posix()}'" for clip_path in clip_paths),
        encoding="utf-8",
    )
    subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_manifest),
            "-c",
            "copy",
            str(assembled_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    video_filters = []
    if project.subtitle_file and Path(project.subtitle_file).exists():
        video_filters.append(
            "subtitles=filename='"
            + _escape_subtitle_path(project.subtitle_file)
            + "':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H60000000,BorderStyle=3,Outline=1,Alignment=2,MarginV=180'"
        )

    final_command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(assembled_path),
        "-i",
        project.voiceover_file,
    ]
    if video_filters:
        final_command.extend(["-vf", ",".join(video_filters)])
    final_command.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            *FINAL_RENDER_ARGS,
            "-shortest",
            str(output_path),
        ]
    )
    try:
        subprocess.run(final_command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"ffmpeg final render failed: {stderr or exc}") from exc

    project.output_file = str(output_path)
    project.status = "ready"
    project.save(update_fields=["output_file", "status", "updated_at"])
    return str(output_path)
