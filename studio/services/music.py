from __future__ import annotations

from pathlib import Path
import math
import random
import hashlib
import shutil
import struct
import subprocess
import wave

from django.conf import settings
import requests

from studio.models import VideoProject
from .utils import media_dir


SAMPLE_RATE = 44100
USER_AGENT = "DarkBrainScrollBot/1.0"
FREEBGMUSIC_API_BASE = "https://freebgmusic.info/api/v1/tracks"


def _resolve_ffmpeg_binary() -> str | None:
    configured = getattr(settings, "FFMPEG_BINARY", "ffmpeg")
    return shutil.which(configured) or (configured if Path(configured).exists() else None)


def _project_render_mode(project: VideoProject) -> str:
    for note in project.topic.source_notes or []:
        if str(note).startswith("render-mode:"):
            return str(note).split(":", 1)[1].strip().lower()
    return str(project.caption_style.get("render_mode") or "").strip().lower()


def _music_vibe(project: VideoProject) -> str:
    for note in project.topic.source_notes or []:
        if str(note).startswith("music-vibe:"):
            return str(note).split(":", 1)[1].strip()
    return ""


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
    track_map = {path.name: path for path in library}
    existing_track = str((project.caption_style or {}).get("music_track") or "").strip()
    if existing_track and existing_track in track_map:
        return track_map[existing_track]

    recent_tracks = set(_recent_music_tracks(limit=min(len(library), 12)))
    available = [path for path in library if path.name not in recent_tracks]
    if not available:
        available = library

    title_seed = sum(ord(char) for char in (project.topic.title or ""))
    style_index = (project.id + title_seed + len(project.topic.script or "")) % len(available)
    selected = available[style_index]
    caption_style = {**(project.caption_style or {}), "music_track": selected.name}
    project.caption_style = caption_style
    project.save(update_fields=["caption_style", "updated_at"])
    return selected


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


def _brainrot_profiles() -> list[dict]:
    return [
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
        {
            "name": "hyperpop",
            "bpm": 144,
            "chords": [(261.63, 329.63, 392.00), (293.66, 369.99, 440.00), (220.00, 277.18, 329.63)],
            "pad_wave": _saw_wave,
            "lead_wave": _sine_wave,
            "kick": 0.42,
            "snare": 0.09,
            "hat": 0.07,
            "arp_divisor": 1,
        },
        {
            "name": "dreamy",
            "bpm": 96,
            "chords": [(164.81, 207.65, 246.94), (196.00, 246.94, 293.66), (220.00, 261.63, 329.63)],
            "pad_wave": _sine_wave,
            "lead_wave": _triangle_wave,
            "kick": 0.18,
            "snare": 0.04,
            "hat": 0.015,
            "arp_divisor": 4,
        },
        {
            "name": "sport",
            "bpm": 138,
            "chords": [(233.08, 293.66, 349.23), (261.63, 329.63, 392.00), (196.00, 246.94, 293.66)],
            "pad_wave": _pulse_wave,
            "lead_wave": _saw_wave,
            "kick": 0.50,
            "snare": 0.11,
            "hat": 0.06,
            "arp_divisor": 2,
        },
    ]


def _recent_music_profiles(limit: int = 8) -> list[str]:
    profiles: list[str] = []
    for item in VideoProject.objects.order_by("-id")[:limit]:
        value = str((item.caption_style or {}).get("music_profile") or "").strip()
        if value:
            profiles.append(value)
    return profiles


def _recent_music_tracks(limit: int = 8) -> list[str]:
    tracks: list[str] = []
    for item in VideoProject.objects.order_by("-id")[:limit]:
        value = str((item.caption_style or {}).get("music_track") or "").strip()
        if value:
            tracks.append(value)
    return tracks


def _recent_music_variants(limit: int = 12) -> list[str]:
    variants: list[str] = []
    for item in VideoProject.objects.order_by("-id")[:limit]:
        value = str((item.caption_style or {}).get("music_variant") or "").strip()
        if value:
            variants.append(value)
    return variants


def _recent_pixabay_audio_ids(limit: int = 24) -> list[str]:
    audio_ids: list[str] = []
    for item in VideoProject.objects.order_by("-id")[:limit]:
        value = str((item.caption_style or {}).get("pixabay_audio_id") or "").strip()
        if value:
            audio_ids.append(value)
    return audio_ids


def _recent_freebgmusic_track_ids(limit: int = 24) -> list[str]:
    track_ids: list[str] = []
    for item in VideoProject.objects.order_by("-id")[:limit]:
        value = str((item.caption_style or {}).get("freebgmusic_track_id") or "").strip()
        if value:
            track_ids.append(value)
    return track_ids


def _freebgmusic_headers() -> dict[str, str]:
    token = str(getattr(settings, "FREEBGMUSIC_API_KEY", "")).strip()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Key"] = token
    return headers


def _freebgmusic_queries(project: VideoProject) -> list[str]:
    vibe = _music_vibe(project)
    title = " ".join(str(project.topic.title or "").split())
    niche = str(project.niche or "").replace("-", " ").strip()
    render_mode = _project_render_mode(project)
    candidates = [
        vibe,
        f"{vibe} instrumental" if vibe else "",
        f"{vibe} background music" if vibe else "",
        f"{niche} background music" if niche else "",
        f"{niche} instrumental" if niche else "",
        "upbeat" if render_mode == "brainrot-video" else "",
        "electronic" if render_mode == "brainrot-video" else "",
        "cinematic",
        "motivational",
        "soundtrack",
        title,
    ]
    queries: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = " ".join(str(item).split()).strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            queries.append(normalized)
    if not queries:
        queries.append("background")
    seed = f"{project.id}|{project.topic.title}|{project.topic.script[:120]}"
    return sorted(queries, key=lambda item: hashlib.sha1(f"{seed}|{item}".encode("utf-8")).hexdigest())


def _freebgmusic_candidates(query: str, page: int = 1, per_page: int = 12) -> list[dict]:
    response = requests.get(
        FREEBGMUSIC_API_BASE,
        params={"search": query, "page": page, "per_page": per_page},
        headers=_freebgmusic_headers(),
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _download_freebgmusic_audio(project: VideoProject, output_path: Path) -> str:
    queries = _freebgmusic_queries(project)
    recent_track_ids = set(_recent_freebgmusic_track_ids())
    page_seed = sum(ord(char) for char in f"{project.id}|{project.topic.title}")
    pages = [1 + ((page_seed + offset) % 3) for offset in range(3)]
    last_error = ""

    for query in queries[:6]:
        for page in pages:
            try:
                candidates = _freebgmusic_candidates(query, page=page, per_page=12)
            except Exception as exc:
                last_error = str(exc)
                continue
            ranked_candidates = sorted(
                candidates,
                key=lambda item: hashlib.sha1(f"{query}|{page}|{item.get('id','')}".encode("utf-8")).hexdigest(),
            )
            for candidate in ranked_candidates:
                track_id = str(candidate.get("id") or "").strip()
                if track_id and track_id in recent_track_ids:
                    continue
                audio_url = str(candidate.get("file_path") or "").strip()
                if not audio_url:
                    continue
                _download_binary(audio_url, output_path)
                _store_music_metadata(
                    project,
                    music_source="freebgmusic",
                    music_query=query,
                    freebgmusic_track_id=track_id,
                    music_track=str(candidate.get("title") or track_id or Path(audio_url).name),
                    music_artist=str(candidate.get("artist") or ""),
                )
                return str(output_path)

    if last_error:
        raise RuntimeError(f"FreeBGMusic lookup failed: {last_error}")
    raise RuntimeError("FreeBGMusic lookup returned no usable tracks for this project.")


def _pixabay_audio_queries(project: VideoProject) -> list[str]:
    vibe = _music_vibe(project)
    title = " ".join(str(project.topic.title or "").split())
    niche = str(project.niche or "").replace("-", " ").strip()
    render_mode = _project_render_mode(project)
    candidates = [
        vibe,
        f"{vibe} background music" if vibe else "",
        f"{niche} background music" if niche else "",
        f"{niche} instrumental" if niche else "",
        "upbeat background music" if render_mode == "brainrot-video" else "",
        "electronic background music" if render_mode == "brainrot-video" else "",
        "cinematic background music",
        "motivational background music",
        "corporate background music",
        title,
    ]
    queries: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = " ".join(str(item).split()).strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            queries.append(normalized)
    if not queries:
        queries.append("background music")

    seed = f"{project.id}|{project.topic.title}|{project.topic.script[:120]}"
    return sorted(queries, key=lambda item: hashlib.sha1(f"{seed}|{item}".encode("utf-8")).hexdigest())


def _extract_pixabay_audio_url(candidate: dict) -> str:
    nested_audio = candidate.get("audio") if isinstance(candidate.get("audio"), dict) else {}
    for key in (
        "url",
        "download_url",
        "downloadUrl",
        "audio_url",
        "audioUrl",
        "preview_url",
        "previewUrl",
        "src",
    ):
        value = candidate.get(key) or nested_audio.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for nested_key in ("mp3", "wav", "ogg"):
        nested_value = nested_audio.get(nested_key)
        if isinstance(nested_value, dict):
            for key in ("url", "download_url", "src"):
                value = nested_value.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _pixabay_audio_candidates(query: str, per_page: int = 10) -> list[dict]:
    token = str(getattr(settings, "PIXABAY_API_KEY", "")).strip()
    if not token:
        return []
    response = requests.get(
        "https://pixabay.com/api/audio/",
        params={
            "key": token,
            "q": query,
            "per_page": per_page,
        },
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    if response.status_code == 403:
        raise RuntimeError(
            "Pixabay audio API denied access to https://pixabay.com/api/audio/ with the current PIXABAY_API_KEY."
        )
    response.raise_for_status()
    payload = response.json()
    hits = payload.get("hits")
    if isinstance(hits, list):
        return hits
    items = payload.get("items")
    if isinstance(items, list):
        return items
    tracks = payload.get("tracks")
    if isinstance(tracks, list):
        return tracks
    return []


def _download_binary(url: str, output_path: Path) -> bool:
    response = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT}, stream=True)
    response.raise_for_status()
    with output_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)
    return output_path.exists() and output_path.stat().st_size > 0


def _download_pixabay_audio(project: VideoProject, output_path: Path) -> str:
    queries = _pixabay_audio_queries(project)
    recent_audio_ids = set(_recent_pixabay_audio_ids())
    last_error = ""

    for query in queries[:6]:
        try:
            candidates = _pixabay_audio_candidates(query, per_page=12)
        except Exception as exc:
            last_error = str(exc)
            if "api/audio/" in last_error.lower() or "denied access" in last_error.lower():
                raise
            continue

        ranked_candidates = sorted(
            candidates,
            key=lambda item: hashlib.sha1(f"{query}|{item.get('id','')}".encode("utf-8")).hexdigest(),
        )
        for candidate in ranked_candidates:
            audio_id = str(candidate.get("id") or "").strip()
            if audio_id and audio_id in recent_audio_ids:
                continue
            audio_url = _extract_pixabay_audio_url(candidate)
            if not audio_url:
                continue
            _download_binary(audio_url, output_path)
            project.caption_style = {
                **(project.caption_style or {}),
                "music_source": "pixabay-audio",
                "music_query": query,
                "pixabay_audio_id": audio_id,
                "music_track": str(candidate.get("name") or candidate.get("title") or audio_id or Path(audio_url).name),
            }
            project.save(update_fields=["caption_style", "updated_at"])
            return str(output_path)

    if last_error:
        raise RuntimeError(f"Pixabay audio lookup failed: {last_error}")
    raise RuntimeError("Pixabay audio lookup returned no usable tracks for this project.")


def _store_music_metadata(project: VideoProject, **updates: str) -> None:
    caption_style = {**(project.caption_style or {})}
    for key, value in updates.items():
        if value:
            caption_style[key] = value
    project.caption_style = caption_style
    project.save(update_fields=["caption_style", "updated_at"])


def _brainrot_variant(project: VideoProject, profile_name: str) -> dict:
    caption_style = project.caption_style or {}
    existing_variant = str(caption_style.get("music_variant") or "").strip()
    if existing_variant:
        parts = existing_variant.split("|")
        if len(parts) == 4:
            try:
                return {
                    "key": existing_variant,
                    "bpm_shift": int(parts[1]),
                    "energy": int(parts[2]),
                    "texture": int(parts[3]),
                }
            except ValueError:
                pass

    candidates: list[dict] = []
    for bpm_shift in (-3, -1, 2, 4):
        for energy in (0, 1, 2):
            for texture in (0, 1, 2):
                candidates.append(
                    {
                        "key": f"{profile_name}|{bpm_shift}|{energy}|{texture}",
                        "bpm_shift": bpm_shift,
                        "energy": energy,
                        "texture": texture,
                    }
                )

    recent_variants = set(_recent_music_variants(limit=min(len(candidates), 16)))
    available = [candidate for candidate in candidates if candidate["key"] not in recent_variants]
    if not available:
        available = candidates

    title_seed = sum(ord(char) for char in (project.topic.title or ""))
    style_index = (project.id + title_seed + len(project.topic.script or "")) % len(available)
    selected = available[style_index]
    project.caption_style = {**caption_style, "music_variant": selected["key"]}
    project.save(update_fields=["caption_style", "updated_at"])
    return selected


def _brainrot_profile(project: VideoProject) -> dict:
    profiles = _brainrot_profiles()
    profile_map = {profile["name"]: profile for profile in profiles}
    existing_profile = str((project.caption_style or {}).get("music_profile") or "").strip()
    if existing_profile in profile_map:
        return profile_map[existing_profile]

    recent_profiles = _recent_music_profiles(limit=len(profiles))
    available = [profile for profile in profiles if profile["name"] not in recent_profiles]
    if not available:
        available = profiles
    title_seed = sum(ord(char) for char in (project.topic.title or ""))
    style_index = (project.id + title_seed + len(project.topic.script or "")) % len(available)
    selected = available[style_index]
    caption_style = {**(project.caption_style or {}), "music_profile": selected["name"]}
    project.caption_style = caption_style
    project.save(update_fields=["caption_style", "updated_at"])
    return selected


def _write_brainrot_wave(project: VideoProject, wav_path: Path) -> None:
    duration = max(60, int(project.duration_seconds or 120))
    total_samples = duration * SAMPLE_RATE
    profile = _brainrot_profile(project)
    variant = _brainrot_variant(project, profile["name"])
    variant_seed = sum(ord(char) for char in variant["key"])
    rng = random.Random((project.id * 7919) + variant_seed)
    bpm = profile["bpm"] + variant["bpm_shift"]
    beat = 60.0 / bpm
    chord_sets = profile["chords"]
    progression_offset = variant_seed % len(chord_sets)
    progression = [
        chord_sets[(progression_offset + index) % len(chord_sets)]
        for index in range(max(4, math.ceil(duration / (beat * 8))))
    ]
    pad_wave = profile["pad_wave"]
    lead_wave = profile["lead_wave"]
    arp_divisor = profile["arp_divisor"]
    energy_boost = 1.0 + (variant["energy"] * 0.08)
    texture_mix = variant["texture"]

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

            sub = math.sin(2 * math.pi * (root / 2) * t) * ((0.08 + ((project.id % 3) * 0.015)) * energy_boost)
            pad = (
                pad_wave(phase_root) * (0.09 + (texture_mix * 0.01))
                + pad_wave(phase_third) * (0.06 + (texture_mix * 0.008))
                + pad_wave(phase_fifth) * (0.05 + (texture_mix * 0.006))
            )
            arp_selector = int((t / (beat / arp_divisor)) % 3)
            arp_multiplier = 2 if bar_phase > 0.5 else 1 + ((project.id % 2) * 0.5) + (texture_mix * 0.1)
            arp_freq = (root, third, fifth)[arp_selector] * arp_multiplier
            arp_phase = (t * arp_freq) % 1.0
            arp = lead_wave(arp_phase) * ((0.025 + ((project.id % 5) * 0.004)) * energy_boost)
            kick = math.sin(2 * math.pi * (48 + kick_env * (28 + (project.id % 7) + (variant["energy"] * 2))) * t) * kick_env * (profile["kick"] * energy_boost)
            snare_noise = (rng.random() * 2.0 - 1.0) * snare_env * (profile["snare"] * (1.0 + texture_mix * 0.12))
            hat_noise = (rng.random() * 2.0 - 1.0) * hat_env * (profile["hat"] * (1.0 + texture_mix * 0.18))
            side_chain = 1.0 - (kick_env * 0.38)

            fade_in = min(1.0, t / 2.0)
            fade_out = min(1.0, max(0.0, (duration - t) / 3.0))
            envelope = fade_in * fade_out

            melodic = (sub + pad + arp) * side_chain
            sample = _soft_clip((melodic + kick + snare_noise + hat_noise) * envelope)
            stereo_spread = 0.92 + 0.08 * math.sin(2 * math.pi * (0.09 + (texture_mix * 0.015)) * t)
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
    freebgmusic_token = str(getattr(settings, "FREEBGMUSIC_API_KEY", "")).strip()
    pixabay_token = str(getattr(settings, "PIXABAY_API_KEY", "")).strip()

    if freebgmusic_token:
        try:
            _download_freebgmusic_audio(project, output_path)
        except Exception as exc:
            fallback_reason = str(exc).strip()
            if pixabay_token:
                try:
                    _download_pixabay_audio(project, output_path)
                except Exception:
                    if _project_render_mode(project) == "brainrot-video":
                        _generate_brainrot_instrumental(project, output_path)
                        _store_music_metadata(
                            project,
                            music_source="generated-fallback",
                            music_error=fallback_reason[:240],
                        )
                    else:
                        local_track = _pick_local_track(project)
                        if local_track:
                            output_path.write_bytes(local_track.read_bytes())
                            _store_music_metadata(
                                project,
                                music_source="local-fallback",
                                music_error=fallback_reason[:240],
                            )
                        else:
                            project.music_file = ""
                            project.save(update_fields=["music_file", "updated_at"])
                            return ""
            elif _project_render_mode(project) == "brainrot-video":
                _generate_brainrot_instrumental(project, output_path)
                _store_music_metadata(
                    project,
                    music_source="generated-fallback",
                    music_error=fallback_reason[:240],
                )
            else:
                local_track = _pick_local_track(project)
                if local_track:
                    output_path.write_bytes(local_track.read_bytes())
                    _store_music_metadata(
                        project,
                        music_source="local-fallback",
                        music_error=fallback_reason[:240],
                    )
                else:
                    project.music_file = ""
                    project.save(update_fields=["music_file", "updated_at"])
                    return ""
    elif pixabay_token:
        try:
            _download_pixabay_audio(project, output_path)
        except Exception as exc:
            fallback_reason = str(exc).strip()
            if _project_render_mode(project) == "brainrot-video":
                _generate_brainrot_instrumental(project, output_path)
                _store_music_metadata(
                    project,
                    music_source="generated-fallback",
                    music_error=fallback_reason[:240],
                )
            else:
                local_track = _pick_local_track(project)
                if local_track:
                    output_path.write_bytes(local_track.read_bytes())
                    _store_music_metadata(
                        project,
                        music_source="local-fallback",
                        music_error=fallback_reason[:240],
                    )
                else:
                    project.music_file = ""
                    project.save(update_fields=["music_file", "updated_at"])
                    return ""
    elif _project_render_mode(project) == "brainrot-video":
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
