from __future__ import annotations

from pathlib import Path
import math
import random
import shutil
import struct
import subprocess
import wave

from django.conf import settings

from studio.models import VideoProject
from .utils import media_dir


SAMPLE_RATE = 44100


def _resolve_ffmpeg_binary() -> str | None:
    configured = getattr(settings, "FFMPEG_BINARY", "ffmpeg")
    return shutil.which(configured) or (configured if Path(configured).exists() else None)


def _project_render_mode(project: VideoProject) -> str:
    for note in project.topic.source_notes or []:
        if str(note).startswith("render-mode:"):
            return str(note).split(":", 1)[1].strip().lower()
    return str(project.caption_style.get("render_mode") or "").strip().lower()


def _local_music_library() -> list[Path]:
    candidates: list[Path] = []
    for folder_name in ("music", "music-library"):
        folder = Path(settings.MEDIA_ROOT) / folder_name
        if not folder.exists():
            continue
        for pattern in ("*.mp3", "*.wav", "*.m4a"):
            candidates.extend(sorted(folder.glob(pattern)))
    return [path for path in candidates if path.is_file()]


def _pick_local_track(project: VideoProject) -> Path | None:
    library = _local_music_library()
    if not library:
        return None
    return library[project.id % len(library)]


def _soft_clip(value: float) -> float:
    return max(-1.0, min(1.0, value * 0.82))


def _triangle_wave(phase: float) -> float:
    cycle = phase % 1.0
    return 4.0 * abs(cycle - 0.5) - 1.0


def _pulse_wave(phase: float, duty: float = 0.28) -> float:
    return 1.0 if (phase % 1.0) < duty else -1.0


def _saw_wave(phase: float) -> float:
    cycle = phase % 1.0
    return (2.0 * cycle) - 1.0


def _sine_wave(phase: float) -> float:
    return math.sin(2 * math.pi * phase)


def _brainrot_profile(project: VideoProject) -> dict:
    title_seed = sum(ord(char) for char in (project.topic.title or ""))
    style_index = (project.id + title_seed) % 5
    profiles = [
        {
            "name": "club",
            "bpm": 126,
            "chords": [(220.00, 277.18, 329.63), (246.94, 311.13, 369.99), (196.00, 246.94, 293.66)],
            "pad_wave": _saw_wave,
            "lead_wave": _pulse_wave,
            "kick": 0.46,
            "snare": 0.13,
            "hat": 0.05,
            "arp_divisor": 2,
        },
        {
            "name": "luxury",
            "bpm": 112,
            "chords": [(174.61, 220.00, 261.63), (196.00, 246.94, 293.66), (220.00, 261.63, 329.63)],
            "pad_wave": _triangle_wave,
            "lead_wave": _sine_wave,
            "kick": 0.34,
            "snare": 0.08,
            "hat": 0.03,
            "arp_divisor": 4,
        },
        {
            "name": "beach",
            "bpm": 104,
            "chords": [(196.00, 246.94, 293.66), (220.00, 277.18, 329.63), (246.94, 293.66, 369.99)],
            "pad_wave": _sine_wave,
            "lead_wave": _triangle_wave,
            "kick": 0.28,
            "snare": 0.06,
            "hat": 0.02,
            "arp_divisor": 4,
        },
        {
            "name": "fitness",
            "bpm": 132,
            "chords": [(246.94, 311.13, 369.99), (220.00, 277.18, 329.63), (261.63, 329.63, 392.00)],
            "pad_wave": _saw_wave,
            "lead_wave": _pulse_wave,
            "kick": 0.48,
            "snare": 0.12,
            "hat": 0.06,
            "arp_divisor": 2,
        },
        {
            "name": "nightlife",
            "bpm": 118,
            "chords": [(155.56, 196.00, 233.08), (174.61, 220.00, 261.63), (185.00, 233.08, 277.18)],
            "pad_wave": _triangle_wave,
            "lead_wave": _saw_wave,
            "kick": 0.40,
            "snare": 0.10,
            "hat": 0.045,
            "arp_divisor": 2,
        },
    ]
    return profiles[style_index]


def _write_brainrot_wave(project: VideoProject, wav_path: Path) -> None:
    duration = max(60, int(project.duration_seconds or 120))
    total_samples = duration * SAMPLE_RATE
    rng = random.Random(project.id * 7919)
    profile = _brainrot_profile(project)
    bpm = profile["bpm"] + (project.id % 4)
    beat = 60.0 / bpm
    chord_sets = profile["chords"]
    progression = [chord_sets[(project.id + index) % len(chord_sets)] for index in range(max(4, math.ceil(duration / (beat * 8))))]
    pad_wave = profile["pad_wave"]
    lead_wave = profile["lead_wave"]
    arp_divisor = profile["arp_divisor"]

    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)

        for index in range(total_samples):
            t = index / SAMPLE_RATE
            section = min(len(progression) - 1, int(t / (beat * 8)))
            root, third, fifth = progression[section]
            phase_root = (t * root) % 1.0
            phase_third = (t * third) % 1.0
            phase_fifth = (t * fifth) % 1.0

            beat_phase = (t % beat) / beat
            bar_phase = (t % (beat * 4)) / (beat * 4)

            kick_env = max(0.0, 1.0 - (beat_phase / 0.24)) if beat_phase < 0.24 else 0.0
            snare_center = 0.5
            snare_env = max(0.0, 1.0 - (abs(beat_phase - snare_center) / 0.12)) if abs(beat_phase - snare_center) < 0.12 else 0.0
            hat_env = max(0.0, 1.0 - (((t % (beat / 2)) / (beat / 2)) / 0.18)) if (t % (beat / 2)) < (beat / 2) * 0.18 else 0.0

            sub = math.sin(2 * math.pi * (root / 2) * t) * (0.08 + ((project.id % 3) * 0.015))
            pad = (
                pad_wave(phase_root) * 0.09
                + pad_wave(phase_third) * 0.06
                + pad_wave(phase_fifth) * 0.05
            )
            arp_selector = int((t / (beat / arp_divisor)) % 3)
            arp_freq = (root, third, fifth)[arp_selector] * (2 if bar_phase > 0.5 else 1 + ((project.id % 2) * 0.5))
            arp_phase = (t * arp_freq) % 1.0
            arp = lead_wave(arp_phase) * (0.025 + ((project.id % 5) * 0.004))
            kick = math.sin(2 * math.pi * (48 + kick_env * (28 + (project.id % 7))) * t) * kick_env * profile["kick"]
            snare_noise = (rng.random() * 2.0 - 1.0) * snare_env * profile["snare"]
            hat_noise = (rng.random() * 2.0 - 1.0) * hat_env * profile["hat"]
            side_chain = 1.0 - (kick_env * 0.38)

            fade_in = min(1.0, t / 2.0)
            fade_out = min(1.0, max(0.0, (duration - t) / 3.0))
            envelope = fade_in * fade_out

            melodic = (sub + pad + arp) * side_chain
            sample = _soft_clip((melodic + kick + snare_noise + hat_noise) * envelope)
            stereo_spread = 0.92 + 0.08 * math.sin(2 * math.pi * 0.09 * t)
            left = int(sample * stereo_spread * 32767)
            right = int(sample * (2 - stereo_spread) * 32767)
            handle.writeframesraw(struct.pack("<hh", left, right))


def _generate_brainrot_instrumental(project: VideoProject, output_path: Path) -> None:
    ffmpeg_path = _resolve_ffmpeg_binary()
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg is required to generate background music.")

    wav_path = output_path.with_suffix(".wav")
    _write_brainrot_wave(project, wav_path)
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(wav_path),
        "-af",
        "highpass=f=35,lowpass=f=12000,acompressor=threshold=-16dB:ratio=2.5:attack=10:release=160,alimiter=limit=0.92",
        "-c:a",
        "mp3",
        "-b:a",
        "192k",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"ffmpeg music generation failed: {stderr or exc}") from exc
    finally:
        if wav_path.exists():
            wav_path.unlink()


def generate_background_music(project: VideoProject) -> str:
    output_dir = media_dir("projects", str(project.id), "audio")
    output_path = output_dir / "background-music.mp3"

    if _project_render_mode(project) == "brainrot-video":
        _generate_brainrot_instrumental(project, output_path)
    else:
        local_track = _pick_local_track(project)
        if local_track:
            output_path.write_bytes(local_track.read_bytes())
        else:
            project.music_file = ""
            project.save(update_fields=["music_file", "updated_at"])
            return ""

    project.music_file = str(output_path)
    project.save(update_fields=["music_file", "updated_at"])
    return str(output_path)
