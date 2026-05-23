from __future__ import annotations

from datetime import datetime
from math import ceil
import json
import re

import requests
from django.conf import settings
from django.utils import timezone

from studio.enums import ContentNiche
from studio.models import EventLog, ViralTopic
from .utils import stable_hash, truncate_text


JSON_ONLY_SYSTEM_PROMPT = (
    "You create viral short-form video topics for YouTube Shorts. "
    "Return valid JSON only. No markdown fences, no commentary."
)


def _content_provider() -> str:
    configured = getattr(settings, "CONTENT_GENERATION_PROVIDER", "auto").strip().lower()
    if configured and configured != "auto":
        return configured
    if getattr(settings, "GEMINI_API_KEY", ""):
        return "gemini"
    if getattr(settings, "OPENAI_API_KEY", ""):
        return "openai"
    raise RuntimeError(
        "No live content generation provider is configured. "
        "Set GEMINI_API_KEY or OPENAI_API_KEY in the environment."
    )


def _default_model_for_provider(provider: str) -> str:
    configured_model = getattr(settings, "CONTENT_GENERATION_MODEL", "").strip()
    if configured_model:
        return configured_model
    if provider == "gemini":
        return "gemini-2.0-flash"
    return getattr(settings, "OPENAI_CONTENT_MODEL", "chat-latest")


def _niche_label(niche: str) -> str:
    try:
        return ContentNiche(niche).label
    except ValueError:
        return niche.replace("-", " ").title()


def _extract_logged_title(log: EventLog) -> str:
    payload_title = (log.payload or {}).get("title", "").strip()
    if payload_title:
        return payload_title
    match = re.search(r"Project '(.+?)' was removed", log.message or "")
    if match:
        return match.group(1).strip()
    return ""


def _recently_used_titles(niche: str, limit: int = 40) -> list[str]:
    current_titles = list(ViralTopic.objects.filter(niche=niche).values_list("title", flat=True))
    log_titles: list[str] = []
    logs = EventLog.objects.filter(
        event_type__in=["project.created", "project.deleted", "publish.success"]
    ).order_by("-created_at")[:limit]
    for log in logs:
        title = _extract_logged_title(log)
        if title:
            log_titles.append(title)
    seen: list[str] = []
    for title in [*current_titles, *log_titles]:
        if title and title not in seen:
            seen.append(title)
    return seen[:limit]


def estimate_duration_seconds(script: str, scene_plan: list[dict] | None = None) -> int:
    words = max(len(script.split()), 1)
    narration_seconds = ceil(words / 2.4)
    if scene_plan:
        scene_seconds = sum(max(int(scene.get("duration", 0) or 0), 3) for scene in scene_plan)
        narration_seconds = max(narration_seconds, scene_seconds)
    return max(20, min(narration_seconds + 2, 75))


def _scene_duration(text: str, is_intro: bool = False, is_cta: bool = False) -> int:
    word_count = len(text.split())
    duration = max(3, min(10, ceil(word_count / 2.8)))
    if is_intro:
        duration = min(10, duration + 1)
    if is_cta:
        duration = max(3, min(5, duration))
    return duration


def build_scene_plan(intro: str, bullets: list[str], cta: str, visuals: list[str] | None = None) -> list[dict]:
    segments = [intro, *bullets, cta]
    visual_hints = list(visuals or [])
    scene_plan: list[dict] = []
    for index, text in enumerate(segments):
        clean_text = text.strip()
        if not clean_text:
            continue
        visual_hint = visual_hints[index].strip() if index < len(visual_hints) and visual_hints[index] else ""
        scene_plan.append(
            {
                "text": clean_text,
                "duration": _scene_duration(
                    clean_text,
                    is_intro=index == 0,
                    is_cta=index == len(segments) - 1,
                ),
                "visual_hint": visual_hint,
            }
        )
    return scene_plan


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_json_object(text: str) -> dict:
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise RuntimeError("Content generator did not return valid JSON.")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Content generator returned malformed JSON.") from exc


def _topic_prompt(niche: str) -> str:
    recent_titles = _recently_used_titles(niche, limit=20)
    local_today = timezone.localtime(timezone.now()).strftime("%B %d, %Y")
    return (
        f"Create 1 original { _niche_label(niche) } YouTube Shorts topic for {local_today}.\n\n"
        "Rules:\n"
        "- Make it feel fresh, clickable, and specific.\n"
        "- Do not reuse or paraphrase these recent titles:\n"
        + ("\n".join(f"  - {title}" for title in recent_titles) if recent_titles else "  - none")
        + "\n"
        "- Return exactly 1 topic.\n"
        "- Keep intro punchy.\n"
        "- Return 4 or 5 bullets only.\n"
        "- Each bullet should be a single spoken beat, not a paragraph.\n"
        "- Hashtags must be relevant and start with #.\n"
        "- Visual hints must be concrete search prompts for stock media.\n"
        "- Avoid generic phrases like 'concept art', 'abstract background', or repeating the title.\n\n"
        "Return JSON in this format:\n"
        "{\n"
        '  "topics": [\n'
        "    {\n"
        '      "title": "...",\n'
        '      "intro": "...",\n'
        '      "bullets": ["...", "...", "...", "..."],\n'
        '      "cta": "...",\n'
        '      "hashtags": ["#...", "#...", "#...", "#...", "#..."],\n'
        '      "asset_packs": ["..."],\n'
        '      "visuals": ["...", "...", "...", "...", "...", "..."]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "The visuals array must match the spoken segments count exactly: intro + each bullet + cta."
    )


def _gemini_generate(prompt: str) -> dict:
    api_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")
    model = _default_model_for_provider("gemini")
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "system_instruction": {"parts": [{"text": JSON_ONLY_SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.9,
                "responseMimeType": "application/json",
            },
        },
        timeout=90,
    )
    if not response.ok:
        try:
            error_message = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            error_message = response.text
        raise RuntimeError(f"Gemini topic generation failed: {truncate_text(error_message, 300)}")
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no content candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise RuntimeError("Gemini returned an empty topic response.")
    return _extract_json_object(text)


def _openai_generate(prompt: str) -> dict:
    api_key = getattr(settings, "OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    model = _default_model_for_provider("openai")
    base_url = getattr(settings, "OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.9,
            "messages": [
                {"role": "system", "content": JSON_ONLY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=90,
    )
    if not response.ok:
        try:
            error_message = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            error_message = response.text
        raise RuntimeError(f"OpenAI-compatible topic generation failed: {truncate_text(error_message, 300)}")
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI-compatible provider returned no choices.")
    message = choices[0].get("message", {})
    text = (message.get("content") or "").strip()
    if not text:
        raise RuntimeError("OpenAI-compatible provider returned empty content.")
    return _extract_json_object(text)


def _generate_topic_payload(niche: str) -> dict:
    provider = _content_provider()
    prompt = _topic_prompt(niche)
    if provider == "gemini":
        return _gemini_generate(prompt)
    if provider in {"openai", "openrouter"}:
        return _openai_generate(prompt)
    raise RuntimeError(f"Unsupported content generation provider: {provider}")


def _normalize_hashtags(raw_hashtags) -> list[str]:
    hashtags: list[str] = []
    for item in list(raw_hashtags or []):
        tag = str(item).strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag.lstrip('#')}"
        if tag.lower() not in {entry.lower() for entry in hashtags}:
            hashtags.append(tag)
    return hashtags[:8]


def _normalize_bullets(raw_bullets) -> list[str]:
    bullets: list[str] = []
    for item in list(raw_bullets or []):
        text = truncate_text(" ".join(str(item).split()), 220)
        if text:
            bullets.append(text)
    return bullets[:5]


def _normalize_visuals(raw_visuals, expected_count: int) -> list[str]:
    visuals: list[str] = []
    for item in list(raw_visuals or []):
        text = truncate_text(" ".join(str(item).split()), 120)
        if text:
            visuals.append(text)
    if not visuals:
        return [""] * expected_count
    if len(visuals) < expected_count:
        visuals.extend([visuals[-1]] * (expected_count - len(visuals)))
    return visuals[:expected_count]


def _normalize_asset_packs(raw_packs) -> list[str]:
    packs: list[str] = []
    for item in list(raw_packs or []):
        text = truncate_text(" ".join(str(item).split()), 80)
        if text and text.lower() not in {entry.lower() for entry in packs}:
            packs.append(text)
    return packs[:6]


def _validate_topic_payload(payload: dict, niche: str) -> dict:
    topics = payload.get("topics")
    if not isinstance(topics, list) or not topics:
        raise RuntimeError("Content generator returned no topics.")
    first_topic = topics[0]
    if not isinstance(first_topic, dict):
        raise RuntimeError("Content generator returned an invalid topic shape.")

    title = truncate_text(" ".join(str(first_topic.get("title", "")).split()), 110)
    intro = truncate_text(" ".join(str(first_topic.get("intro", "")).split()), 180)
    cta = truncate_text(" ".join(str(first_topic.get("cta", "")).split()), 180)
    bullets = _normalize_bullets(first_topic.get("bullets", []))
    if not title or not intro or not cta or len(bullets) < 4:
        raise RuntimeError("Content generator returned incomplete topic content.")

    visuals = _normalize_visuals(first_topic.get("visuals", []), expected_count=len(bullets) + 2)
    return {
        "title": title,
        "intro": intro,
        "bullets": bullets,
        "cta": cta,
        "hashtags": _normalize_hashtags(first_topic.get("hashtags", [])),
        "asset_packs": _normalize_asset_packs(first_topic.get("asset_packs", [])),
        "visuals": visuals,
        "provider": _content_provider(),
        "model": _default_model_for_provider(_content_provider()),
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "niche": niche,
    }


def build_ai_topic(niche: str) -> ViralTopic:
    payload = _validate_topic_payload(_generate_topic_payload(niche), niche)
    script_lines = [payload["intro"], *payload["bullets"], payload["cta"]]
    script = "\n".join(script_lines)
    scene_plan = build_scene_plan(payload["intro"], payload["bullets"], payload["cta"], visuals=payload["visuals"])
    duration_seconds = estimate_duration_seconds(script, scene_plan)
    content_signature = stable_hash([niche, payload["title"].strip().lower(), " ".join(script.lower().split())])
    return ViralTopic.objects.create(
        niche=niche,
        title=payload["title"],
        hook=payload["intro"],
        script=script,
        scene_plan=scene_plan,
        seo_title=f'{payload["title"]} | {getattr(settings, "CHANNEL_BRAND_NAME", "DarkBrainScroll")}',
        description=script,
        hashtags=payload["hashtags"] or [f"#{niche}", "#shorts", "#viral"],
        source_notes=[
            f"provider:{payload['provider']}",
            f"model:{payload['model']}",
            f"generated-at:{payload['generated_at']}",
            f"estimated-duration:{duration_seconds}",
            f"content-signature:{content_signature}",
            *[f"asset-pack:{pack}" for pack in payload["asset_packs"]],
        ],
        is_trending=False,
    )
