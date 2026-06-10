from __future__ import annotations

from datetime import datetime
from math import ceil
import json
import re
from typing import Any

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

LONGFORM_JSON_ONLY_SYSTEM_PROMPT = (
    "You create viral long-form YouTube video topics. "
    "Return valid JSON only. No markdown fences, no commentary."
)

DARK_CURIOSITY_CATEGORIES = [
    "Unexplained Mysteries",
    "Ancient Secrets",
    "Strange Science",
    "Hidden History",
    "Dangerous Places",
    "Weird Animals",
    "Space Mysteries",
    "Internet Mysteries",
    "Lost Civilizations",
    "Unsolved Events",
]

DARK_CURIOSITY_CATEGORY_ALIASES = {
    "unexplained mystery": "Unexplained Mysteries",
    "unexplained mysteries": "Unexplained Mysteries",
    "ancient secret": "Ancient Secrets",
    "ancient secrets": "Ancient Secrets",
    "strange science": "Strange Science",
    "hidden history": "Hidden History",
    "dangerous place": "Dangerous Places",
    "dangerous places": "Dangerous Places",
    "weird animal": "Weird Animals",
    "weird animals": "Weird Animals",
    "space mystery": "Space Mysteries",
    "space mysteries": "Space Mysteries",
    "internet mystery": "Internet Mysteries",
    "internet mysteries": "Internet Mysteries",
    "lost civilization": "Lost Civilizations",
    "lost civilizations": "Lost Civilizations",
    "unsolved event": "Unsolved Events",
    "unsolved events": "Unsolved Events",
}

DARK_CURIOSITY_RULES = (
    "Primary goal:\n"
    "- Maximize retention, curiosity, rewatches, shares, and comments.\n"
    "- Generate content only in the Dark Curiosity niche.\n"
    "Topic selection:\n"
    "- Pick exactly 1 category from this list: " + ", ".join(DARK_CURIOSITY_CATEGORIES) + ".\n"
    "- Build a topic using one of these formulas:\n"
    "  1. [UNEXPLAINED] + [DANGER] + [REAL EVENT]\n"
    "  2. [ANCIENT] + [MYSTERY] + [MODERN DISCOVERY]\n"
    "- Favor titles like: The Cave Nobody Returned From, The Signal Scientists Can't Decode, The Island Humans Can't Visit, The Ancient Machine Found Underground.\n"
    "Script structure:\n"
    "- Total runtime must land between 35 and 50 seconds.\n"
    "- Hook covers 0 to 3 seconds and must create immediate curiosity.\n"
    "- Story build covers roughly 3 to 25 seconds and must increase tension without revealing the answer too early.\n"
    "- Twist lands roughly 25 to 40 seconds and reveals the shocking fact.\n"
    "- Final line must end with unresolved mystery, uncertainty, or an open question.\n"
    "Retention rules:\n"
    "- Every 3 to 5 seconds introduce a new mystery, shocking detail, unexpected fact, or unanswered question.\n"
    "- Never allow more than 2 consecutive spoken lines without a curiosity trigger.\n"
    "- Keep each spoken line crisp, clear, and easy to understand on first listen.\n"
    "- Do not use filler, generic educational framing, or slow setup.\n"
    "Output rules:\n"
    "- Return 6 to 8 body beats.\n"
    "- Generate exactly 20 Pixabay search keywords.\n"
    "- Score Curiosity, Shock, Retention, and Shareability from 1 to 10.\n"
    "- Reject weak ideas internally and only return topics where every score is at least 8.\n"
    "- Keep everything platform-safe and avoid graphic gore.\n"
)

SIMILARITY_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "what",
    "why",
    "with",
    "you",
    "your",
}


def _content_provider() -> str:
    return getattr(settings, "CONTENT_GENERATION_PROVIDER", "auto").strip().lower() or "auto"


def _default_model_for_provider(provider: str) -> str:
    configured_model = getattr(settings, "CONTENT_GENERATION_MODEL", "").strip()
    configured_provider = _content_provider()
    if configured_model and configured_provider == provider:
        return configured_model
    if provider == "gemini":
        return "gemini-2.0-flash"
    if provider == "openrouter":
        models = getattr(settings, "OPENROUTER_CONTENT_MODELS", []) or ["x-ai/grok-beta"]
        return models[0]
    if provider == "groq":
        models = getattr(settings, "GROQ_CONTENT_MODELS", []) or ["llama-3.3-70b-versatile"]
        return models[0]
    if provider == "huggingface":
        models = getattr(settings, "HUGGINGFACE_CONTENT_MODELS", []) or ["microsoft/Phi-3-mini-4k-instruct"]
        return models[0]
    return getattr(settings, "OPENAI_CONTENT_MODEL", "chat-latest")


def _provider_api_key(provider: str) -> str:
    key_map = {
        "gemini": getattr(settings, "GEMINI_API_KEY", ""),
        "openai": getattr(settings, "OPENAI_API_KEY", ""),
        "openrouter": getattr(settings, "OPENROUTER_API_KEY", ""),
        "groq": getattr(settings, "GROQ_API_KEY", ""),
        "huggingface": getattr(settings, "HUGGINGFACE_TOKEN", ""),
    }
    return str(key_map.get(provider, "")).strip()


def _provider_enabled(provider: str) -> bool:
    return bool(_provider_api_key(provider))


def _provider_models(provider: str) -> list[str]:
    if provider == "openrouter":
        return list(getattr(settings, "OPENROUTER_CONTENT_MODELS", []) or [_default_model_for_provider(provider)])
    if provider == "groq":
        return list(getattr(settings, "GROQ_CONTENT_MODELS", []) or [_default_model_for_provider(provider)])
    if provider == "huggingface":
        return list(getattr(settings, "HUGGINGFACE_CONTENT_MODELS", []) or [_default_model_for_provider(provider)])
    return [_default_model_for_provider(provider)]


def _provider_base_url(provider: str) -> str:
    if provider == "openrouter":
        return getattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    if provider == "groq":
        return getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    if provider == "huggingface":
        return getattr(settings, "HUGGINGFACE_BASE_URL", "https://api-inference.huggingface.co/v1").rstrip("/")
    return getattr(settings, "OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _provider_order() -> list[str]:
    configured = _content_provider()
    default_order = ["gemini", "openrouter", "groq", "openai", "huggingface"]
    if configured == "auto":
        return default_order
    if configured not in default_order:
        raise RuntimeError(f"Unsupported content generation provider: {configured}")
    return [configured, *[provider for provider in default_order if provider != configured]]


def _generation_candidates() -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    allow_fallbacks = getattr(settings, "CONTENT_GENERATION_ALLOW_FALLBACKS", True)
    configured_provider = _content_provider()
    for provider in _provider_order():
        if not _provider_enabled(provider):
            continue
        for model in _provider_models(provider):
            key = (provider, model)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "provider": provider,
                    "model": model,
                    "api_key": _provider_api_key(provider),
                    "base_url": _provider_base_url(provider),
                }
            )
        if configured_provider != "auto" and not allow_fallbacks:
            break
    if candidates:
        return candidates
    raise RuntimeError(
        "No live content generation provider is configured. "
        "Set at least one of GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, or HUGGINGFACE_TOKEN."
    )


def _niche_label(niche: str) -> str:
    try:
        return ContentNiche(niche).label
    except ValueError:
        return niche.replace("-", " ").title()


def _niche_prompt_profile(niche: str) -> dict[str, str]:
    profiles = {
        str(ContentNiche.CARS): {
            "angle": "viral car culture, launches, comparisons, hidden features, and enthusiast debate",
            "formats": "new launch reactions, dream car comparisons, fastest feature breakdowns, ownership facts, viral car myths",
            "visuals": "cars, interiors, driving shots, showrooms, dashboards, roads, close-up detail shots",
        },
        str(ContentNiche.TOP_10_CARS): {
            "angle": "ranked car countdowns built for scroll retention",
            "formats": "top 10 fastest, top 10 luxury, top 10 budget beasts, top 10 crazy designs",
            "visuals": "ranked car clips, thumbnails, garages, speed shots, cinematic transitions",
        },
        str(ContentNiche.CAR_FACTS): {
            "angle": "surprising car facts, innovations, pricing hooks, and buyer psychology",
            "formats": "did you know car facts, hidden buttons, expensive mistakes, future tech",
            "visuals": "dashboard closeups, steering wheels, engines, headlights, car factories",
        },
        str(ContentNiche.CAR_NEWS): {
            "angle": "timely car launches, brand moves, price talk, and hype-worthy updates",
            "formats": "launch buzz, leaked specs style videos, what changed this year, buying hype",
            "visuals": "showroom reveals, press event style visuals, concept cars, test drives",
        },
        str(ContentNiche.LUXURY_CARS): {
            "angle": "luxury lifestyle cars, status, interiors, and premium features",
            "formats": "most expensive interiors, luxury vs budget, insane optional extras",
            "visuals": "premium cabins, leather details, city night drives, luxury garages",
        },
        str(ContentNiche.SUPERCARS): {
            "angle": "supercar speed, sound, rarity, flex appeal, and dream-garage energy",
            "formats": "fastest supercars, insane price tags, rare editions, sound comparisons",
            "visuals": "supercars revving, track shots, spoilers, carbon fiber, exotic dealerships",
        },
        str(ContentNiche.CUTE_ANIMALS): {
            "angle": "cute, wholesome, highly shareable animal content",
            "formats": "cute moments, cutest species facts, baby animal story beats, wholesome reactions",
            "visuals": "puppies, kittens, baby animals, rescue clips, playful wildlife",
        },
        str(ContentNiche.ANIMALS): {
            "angle": "wild animal behavior, unusual species, survival, and surprising facts",
            "formats": "most dangerous habits, weird animal skills, animals you did not know existed",
            "visuals": "wildlife footage, jungle, ocean, safari, macro animal shots",
        },
        str(ContentNiche.ANIMAL_FACTS): {
            "angle": "fast, fascinating animal facts with strong rewatch value",
            "formats": "crazy facts, animal myths vs truth, top survival tricks, rare species",
            "visuals": "close-up wildlife, nature landscapes, pack behavior, underwater scenes",
        },
        str(ContentNiche.CELEBRITY): {
            "angle": "celebrity moments, glow-ups, career twists, and pop culture hooks",
            "formats": "before fame, wild success facts, celebrity transformations, iconic moments",
            "visuals": "red carpet style footage, paparazzi vibe, stage lights, fan crowds",
        },
        str(ContentNiche.CELEBRITY_GOSSIP): {
            "angle": "light, platform-safe celebrity buzz and internet chatter",
            "formats": "rumor roundup style, viral celeb moments, surprise collabs, public reactions",
            "visuals": "award shows, fan cameras, headlines, glam portraits, crowd reactions",
        },
        str(ContentNiche.CELEBRITY_FACTS): {
            "angle": "surprising celebrity facts, money, habits, and hidden backstories",
            "formats": "unknown facts, luxury habits, odd routines, career pivots",
            "visuals": "spotlight stages, interviews, backstage scenes, portrait style clips",
        },
        str(ContentNiche.DANCE): {
            "angle": "dance trends, challenge culture, glow-up edits, and hype energy",
            "formats": "viral dance challenge ideas, easy trend moves, best performance hooks",
            "visuals": "dance rehearsals, stage lights, silhouettes, motion closeups",
        },
        str(ContentNiche.GLAM): {
            "angle": "glam creator energy, beauty, fashion, dance, and social-ready style",
            "formats": "look breakdowns, glow-up hooks, style secrets, creator trend angles",
            "visuals": "fashion shoots, mirror shots, makeup details, performance clips",
        },
        str(ContentNiche.STORY): {
            "angle": "emotion-driven short stories with strong hook and payoff",
            "formats": "twist stories, lesson stories, emotional confessions, micro-story arcs",
            "visuals": "cinematic b-roll, city streets, emotional closeups, silhouettes",
        },
        str(ContentNiche.HORROR): {
            "angle": "creepy but platform-safe horror stories and suspense hooks",
            "formats": "2 sentence horror expanded, true-story style scares, unknown caller, haunted place hooks",
            "visuals": "dark hallways, shadows, empty streets, fog, creepy interiors",
        },
        str(ContentNiche.MEME): {
            "angle": "fast meme culture, relatable internet humor, and comment bait",
            "formats": "relatable situations, trending joke formats, POV memes, chaotic comparisons",
            "visuals": "reaction faces, exaggerated edits, funny stock clips, text-heavy meme setups",
        },
    }
    return profiles.get(
        niche,
        {
            "angle": f"viral {_niche_label(niche).lower()} content",
            "formats": "fact-based hooks, trend-inspired list angles, comparison videos, story-driven shorts",
            "visuals": "stock footage that clearly matches the niche and each spoken beat",
        },
    )


def _default_hashtags_for_niche(niche: str, *, longform: bool = False) -> list[str]:
    base = [f"#{word}" for word in re.findall(r"[a-z0-9]+", niche.replace("-", " ").lower())[:2]]
    if niche == str(ContentNiche.DARK_CURIOSITY):
        return ["#darkcuriosity", "#mystery", "#youtube", "#storytelling"] if longform else ["#darkcuriosity", "#mystery", "#shorts", "#viral"]
    common = ["#viral", "#trending", "#fyp", "#youtube"] if longform else ["#viral", "#trending", "#shorts", "#fyp"]
    return [*base, *common][:4]


def _extract_logged_title(log: EventLog) -> str:
    payload_title = (log.payload or {}).get("title", "").strip()
    if payload_title:
        return payload_title
    match = re.search(r"Project '(.+?)' was removed", log.message or "")
    if match:
        return match.group(1).strip()
    return ""


def _recently_used_titles(niche: str | None, limit: int = 40) -> list[str]:
    topic_query = ViralTopic.objects.all()
    if niche:
        topic_query = topic_query.filter(niche=niche)
    current_titles = list(topic_query.values_list("title", flat=True))
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


def _normalize_similarity_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def _normalize_dark_curiosity_category(category: str) -> str:
    cleaned = truncate_text(" ".join(str(category or "").split()), 80)
    if not cleaned:
        return DARK_CURIOSITY_CATEGORIES[0]
    if cleaned in DARK_CURIOSITY_CATEGORIES:
        return cleaned

    normalized = _normalize_similarity_text(cleaned)
    if normalized in DARK_CURIOSITY_CATEGORY_ALIASES:
        return DARK_CURIOSITY_CATEGORY_ALIASES[normalized]

    for candidate in DARK_CURIOSITY_CATEGORIES:
        candidate_normalized = _normalize_similarity_text(candidate)
        if normalized == candidate_normalized:
            return candidate
        if normalized in candidate_normalized or candidate_normalized in normalized:
            return candidate
    return DARK_CURIOSITY_CATEGORIES[0]


def _tokenize_similarity_text(value: str) -> set[str]:
    tokens = {
        token
        for token in _normalize_similarity_text(value).split()
        if len(token) >= 3 and token not in SIMILARITY_STOP_WORDS
    }
    return tokens


def _topic_similarity(left: str, right: str) -> float:
    left_tokens = _tokenize_similarity_text(left)
    right_tokens = _tokenize_similarity_text(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    return len(overlap) / max(min(len(left_tokens), len(right_tokens)), 1)


def _topic_brief(topic: ViralTopic) -> str:
    script_lines = [line.strip() for line in str(topic.script or "").splitlines() if line.strip()]
    preview = " | ".join(script_lines[:3])
    return f"{topic.title.strip()} :: {preview}".strip()


def _recent_topic_briefs(niche: str | None, limit: int = 20) -> list[str]:
    briefs: list[str] = []
    topic_query = ViralTopic.objects.all()
    if niche:
        topic_query = topic_query.filter(niche=niche)
    topics = topic_query.order_by("-created_at")[:limit]
    for topic in topics:
        brief = _topic_brief(topic)
        if brief:
            briefs.append(brief)
    logs = EventLog.objects.filter(
        event_type__in=["project.created", "project.deleted", "publish.success"]
    ).order_by("-created_at")[:limit]
    for log in logs:
        title = _extract_logged_title(log)
        if not title:
            continue
        brief = title.strip()
        if brief and brief not in briefs:
            briefs.append(brief)
    return briefs[:limit]


def estimate_duration_seconds(script: str, scene_plan: list[dict] | None = None) -> int:
    words = max(len(script.split()), 1)
    narration_seconds = ceil(words / 2.8)
    if scene_plan:
        scene_seconds = sum(max(int(scene.get("duration", 0) or 0), 3) for scene in scene_plan)
        narration_seconds = max(narration_seconds, scene_seconds)
    return max(35, min(narration_seconds + 1, 50))


def estimate_longform_duration_seconds(script: str, scene_plan: list[dict] | None = None) -> int:
    words = max(len(script.split()), 1)
    narration_seconds = ceil(words / 2.55)
    minimum = max(120, int(getattr(settings, "LONGFORM_MIN_DURATION_SECONDS", 180)))
    maximum = max(minimum, int(getattr(settings, "LONGFORM_MAX_DURATION_SECONDS", 300)))
    if scene_plan:
        scene_seconds = sum(max(int(scene.get("duration", 0) or 0), 6) for scene in scene_plan)
        narration_seconds = max(narration_seconds, scene_seconds)
    return max(minimum, min(narration_seconds + 2, maximum))


def _scene_duration(text: str, is_intro: bool = False, is_cta: bool = False) -> int:
    word_count = len(text.split())
    duration = max(3, min(7, ceil(word_count / 3.1)))
    if is_intro:
        duration = min(4, max(3, duration))
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
    recent_titles = _recently_used_titles(None, limit=20)
    recent_briefs = _recent_topic_briefs(None, limit=12)
    local_today = timezone.localtime(timezone.now()).strftime("%B %d, %Y")
    niche_label = _niche_label(niche)
    profile = _niche_prompt_profile(niche)
    prompt = f"Create 1 original trending {niche_label} YouTube Shorts idea for {local_today}.\n\n"
    prompt += "Rules:\n"
    if niche == str(ContentNiche.DARK_CURIOSITY):
        prompt += DARK_CURIOSITY_RULES
    else:
        prompt += f"- Stay fully inside the {niche_label} niche.\n"
        prompt += f"- The topic must feel like it could trend right now in {profile['angle']}.\n"
        prompt += f"- Prefer formats like: {profile['formats']}.\n"
        prompt += "- Make it highly clickable, curiosity-driven, specific, and easy to understand on first listen.\n"
        prompt += "- Focus on ideas with high views potential, strong hook rate, retention, and shareability.\n"
        prompt += "- Do not make unverifiable breaking-news claims unless framed as a general trend angle.\n"
        prompt += "- Return 6 to 8 bullets.\n"
        prompt += "- Each bullet should be one spoken beat, not a paragraph.\n"
        prompt += "- The full script should land around 35 to 50 seconds when spoken naturally.\n"
        prompt += f"- Visual hints should be concrete stock-footage-friendly prompts using {profile['visuals']}.\n"
        prompt += "- Generate exactly 20 useful Pixabay keywords.\n"
        prompt += "- Score Curiosity, Shock, Retention, and Shareability from 1 to 10.\n"
    prompt += "- Make it feel fresh, clickable, specific, and impossible to skip.\n"
    prompt += "- Build the topic around a trending idea, trend-style angle, or high-demand viewer curiosity.\n"
    prompt += "- Do not reuse or paraphrase these recent titles:\n"
    prompt += "\n".join(f"  - {title}" for title in recent_titles) if recent_titles else "  - none"
    prompt += "\n"
    prompt += "- Do not reuse the same hook, angle, structure, examples, or payoff from these recent ideas:\n"
    prompt += "\n".join(f"  - {brief}" for brief in recent_briefs) if recent_briefs else "  - none"
    prompt += "\n"
    prompt += "- Return exactly 1 topic.\n"
    prompt += "- Keep the hook punchy and immediate.\n"
    prompt += "- Return 6 to 8 bullets.\n"
    prompt += "- Each bullet should be a single spoken beat, not a paragraph.\n"
    prompt += "- Make the full script land around 35 to 50 seconds when spoken naturally.\n"
    prompt += "- Make each spoken beat clear on first listen, with fast context and escalating tension.\n"
    prompt += "- The topic must be meaningfully different from the recent ideas, not just a reworded version.\n"
    prompt += "- Hashtags must be relevant and start with #.\n"
    prompt += "- Visual hints must be concrete search prompts for stock media.\n"
    prompt += "- Pixabay keywords must be short, concrete, and useful for stock search.\n"
    prompt += "- Avoid generic phrases like 'concept art', 'abstract background', or repeating the title.\n\n"
    prompt += "Return JSON in this format:\n"
    prompt += "{\n"
    prompt += '  "topics": [\n'
    prompt += "    {\n"
    prompt += '      "category": "...",\n'
    prompt += '      "topic_formula": "...",\n'
    prompt += '      "title": "...",\n'
    prompt += '      "intro": "...",\n'
    prompt += '      "bullets": ["...", "...", "...", "...", "...", "..."],\n'
    prompt += '      "cta": "...",\n'
    prompt += '      "hashtags": ["#...", "#...", "#...", "#...", "#..."],\n'
    prompt += '      "asset_packs": ["..."],\n'
    prompt += '      "visuals": ["...", "...", "...", "...", "...", "...", "...", "..."],\n'
    prompt += '      "pixabay_keywords": ["...", "..."],\n'
    prompt += '      "viral_scores": {"curiosity": 8, "shock": 8, "retention": 8, "shareability": 8}\n'
    prompt += "    }\n"
    prompt += "  ]\n"
    prompt += "}\n"
    prompt += "The visuals array must match the spoken segments count exactly: intro + each bullet + cta."
    return prompt


def _brainrot_video_prompt() -> str:
    return _topic_prompt(str(ContentNiche.DARK_CURIOSITY))


def _longform_topic_prompt(niche: str) -> str:
    recent_titles = _recently_used_titles(None, limit=20)
    recent_briefs = _recent_topic_briefs(None, limit=12)
    local_today = timezone.localtime(timezone.now()).strftime("%B %d, %Y")
    niche_label = _niche_label(niche)
    profile = _niche_prompt_profile(niche)
    prompt = f"Create 1 original trending {niche_label} long-form YouTube video idea for {local_today}.\n\n"
    prompt += "Rules:\n"
    if niche == str(ContentNiche.DARK_CURIOSITY):
        prompt += "- Stay fully inside the Dark Curiosity niche.\n"
        prompt += "- Structure the story as a layered mystery with rising stakes, evidence, twists, and an unresolved ending.\n"
        prompt += "- Use a documentary storytelling tone, not listicle filler.\n"
        prompt += "- Pixabay keywords must be short and useful for dark mystery stock footage searches.\n"
    else:
        prompt += f"- Stay fully inside the {niche_label} niche.\n"
        prompt += f"- The idea should feel built for high-demand viewers interested in {profile['angle']}.\n"
        prompt += f"- Prefer a format like {profile['formats']}.\n"
        prompt += "- Use a story-led explainer tone instead of shallow filler.\n"
        prompt += f"- Include stock-footage-friendly visuals using {profile['visuals']}.\n"
        prompt += "- Pixabay keywords must be short and useful for this niche.\n"
    prompt += "- The final spoken script must feel built for a 3 to 5 minute horizontal YouTube video.\n"
    prompt += "- Open with a strong hook in the first 10 seconds.\n"
    prompt += "- Keep each spoken beat concise, vivid, and easy to narrate.\n"
    prompt += "- Return 12 to 18 body beats so the edit has enough visual variety.\n"
    prompt += "- Include concrete stock-footage friendly visual hints for every spoken segment.\n"
    prompt += "- Hashtags must be relevant and start with #.\n"
    prompt += "- Do not reuse or closely paraphrase these recent titles:\n"
    prompt += "\n".join(f"  - {title}" for title in recent_titles) if recent_titles else "  - none"
    prompt += "\n"
    prompt += "- Do not reuse the same angle, reveal, or evidence trail from these recent ideas:\n"
    prompt += "\n".join(f"  - {brief}" for brief in recent_briefs) if recent_briefs else "  - none"
    prompt += "\n"
    prompt += "- The topic must be meaningfully different from the recent ideas.\n"
    prompt += "- Avoid generic 'top 10' framing or filler transitions.\n\n"
    prompt += "Return JSON in this format:\n"
    prompt += "{\n"
    prompt += '  "topics": [\n'
    prompt += "    {\n"
    prompt += '      "category": "...",\n'
    prompt += '      "topic_formula": "...",\n'
    prompt += '      "title": "...",\n'
    prompt += '      "intro": "...",\n'
    prompt += '      "bullets": ["...", "..."],\n'
    prompt += '      "cta": "...",\n'
    prompt += '      "hashtags": ["#...", "#..."],\n'
    prompt += '      "asset_packs": ["..."],\n'
    prompt += '      "visuals": ["...", "..."],\n'
    prompt += '      "pixabay_keywords": ["...", "..."],\n'
    prompt += '      "viral_scores": {"curiosity": 8, "shock": 8, "retention": 8, "shareability": 8}\n'
    prompt += "    }\n"
    prompt += "  ]\n"
    prompt += "}\n"
    prompt += "The visuals array must match the spoken segments count exactly: intro + each bullet + cta."
    return prompt


def _gemini_generate(prompt: str) -> dict:
    api_key = _provider_api_key("gemini")
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


def _gemini_generate_with_system_prompt(prompt: str, system_prompt: str) -> dict:
    api_key = _provider_api_key("gemini")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")
    model = _default_model_for_provider("gemini")
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "system_instruction": {"parts": [{"text": system_prompt}]},
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


def _extract_message_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts: list[str] = []
        for item in message:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts).strip()
    if isinstance(message, dict):
        content = message.get("content")
        if content is not None:
            return _extract_message_text(content)
    return ""


def _openai_compatible_generate(prompt: str, *, provider: str, model: str, base_url: str, api_key: str) -> dict:
    return _openai_compatible_generate_with_system_prompt(
        prompt,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prompt=JSON_ONLY_SYSTEM_PROMPT,
    )


def _openai_compatible_generate_with_system_prompt(
    prompt: str,
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
) -> dict:
    if not api_key:
        raise RuntimeError(f"{provider.title()} API key is missing.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = getattr(settings, "APP_BASE_URL", "http://127.0.0.1:8000")
        headers["X-Title"] = getattr(settings, "CHANNEL_BRAND_NAME", "DarkBrainScroll")
    response = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "temperature": 0.9,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
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
        raise RuntimeError(f"{provider.title()} topic generation failed: {truncate_text(error_message, 300)}")
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"{provider.title()} returned no choices.")
    message = choices[0].get("message", {})
    text = _extract_message_text(message.get("content"))
    if not text:
        raise RuntimeError(f"{provider.title()} returned empty content.")
    return _extract_json_object(text)


def _generate_topic_payload(niche: str) -> tuple[dict, str, str]:
    prompt = _topic_prompt(niche)
    failures: list[str] = []
    for candidate in _generation_candidates():
        provider = candidate["provider"]
        model = candidate["model"]
        try:
            if provider == "gemini":
                return _gemini_generate(prompt), provider, model
            if provider in {"openai", "openrouter", "groq", "huggingface"}:
                return (
                    _openai_compatible_generate(
                        prompt,
                        provider=provider,
                        model=model,
                        base_url=candidate["base_url"],
                        api_key=candidate["api_key"],
                    ),
                    provider,
                    model,
                )
            failures.append(f"{provider}/{model}: unsupported provider")
        except Exception as exc:
            failures.append(f"{provider}/{model}: {truncate_text(str(exc), 220)}")
    raise RuntimeError("All topic generation providers failed. " + " | ".join(failures))


def _generate_custom_topic_payload(prompt: str) -> tuple[dict, str, str]:
    return _generate_custom_topic_payload_with_system_prompt(prompt, JSON_ONLY_SYSTEM_PROMPT)


def _generate_custom_topic_payload_with_system_prompt(prompt: str, system_prompt: str) -> tuple[dict, str, str]:
    failures: list[str] = []
    for candidate in _generation_candidates():
        provider = candidate["provider"]
        model = candidate["model"]
        try:
            if provider == "gemini":
                return _gemini_generate_with_system_prompt(prompt, system_prompt), provider, model
            if provider in {"openai", "openrouter", "groq", "huggingface"}:
                return (
                    _openai_compatible_generate_with_system_prompt(
                        prompt,
                        provider=provider,
                        model=model,
                        base_url=candidate["base_url"],
                        api_key=candidate["api_key"],
                        system_prompt=system_prompt,
                    ),
                    provider,
                    model,
                )
            failures.append(f"{provider}/{model}: unsupported provider")
        except Exception as exc:
            failures.append(f"{provider}/{model}: {truncate_text(str(exc), 220)}")
    raise RuntimeError("All topic generation providers failed. " + " | ".join(failures))


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


def _normalize_bullets(raw_bullets, limit: int = 5) -> list[str]:
    bullets: list[str] = []
    for item in list(raw_bullets or []):
        text = truncate_text(" ".join(str(item).split()), 220)
        if text:
            bullets.append(text)
    return bullets[:limit]


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


def _normalize_searches(raw_searches, limit: int = 12) -> list[str]:
    searches: list[str] = []
    for item in list(raw_searches or []):
        text = truncate_text(" ".join(str(item).split()), 100)
        if text and text.lower() not in {entry.lower() for entry in searches}:
            searches.append(text)
    return searches[:limit]


def _normalize_pixabay_keywords(raw_keywords, limit: int = 20) -> list[str]:
    keywords: list[str] = []
    for item in list(raw_keywords or []):
        text = truncate_text(" ".join(str(item).split()), 60)
        if text and text.lower() not in {entry.lower() for entry in keywords}:
            keywords.append(text)
    return keywords[:limit]


def _expand_pixabay_keywords(
    existing_keywords: list[str],
    *,
    title: str,
    category: str,
    topic_formula: str,
    intro: str,
    bullets: list[str],
    visuals: list[str],
    limit: int = 20,
) -> list[str]:
    keywords: list[str] = []

    def add(value: str) -> None:
        text = truncate_text(" ".join(str(value).split()), 60)
        if text and text.lower() not in {entry.lower() for entry in keywords}:
            keywords.append(text)

    for item in existing_keywords:
        add(item)

    for item in [title, category, topic_formula, intro, *bullets, *visuals]:
        words = [word for word in re.split(r"[^a-zA-Z0-9]+", str(item).lower()) if len(word) >= 3]
        phrase_words: list[str] = []
        for word in words:
            if word in SIMILARITY_STOP_WORDS or word in phrase_words:
                continue
            phrase_words.append(word)
            if len(phrase_words) >= 3:
                break
        if phrase_words:
            add(" ".join(phrase_words))

    fallback_pool = [
        "mystery",
        "dark mystery",
        "ancient ruins",
        "abandoned place",
        "hidden history",
        "space signal",
        "deep ocean",
        "lost civilization",
        "unexplained event",
        "dangerous place",
        "mysterious forest",
        "secret tunnel",
        "strange science",
        "ancient artifact",
        "underground chamber",
        "foggy landscape",
        "deserted street",
        "documentary footage",
        "mystery landscape",
        "unknown signal",
    ]
    for item in fallback_pool:
        add(item)
        if len(keywords) >= limit:
            break

    return keywords[:limit]


def _normalize_viral_scores(raw_scores) -> dict[str, int]:
    default_scores = {"curiosity": 0, "shock": 0, "retention": 0, "shareability": 0}
    if not isinstance(raw_scores, dict):
        return default_scores
    normalized: dict[str, int] = {}
    for key in default_scores:
        try:
            normalized[key] = int(raw_scores.get(key, 0))
        except (TypeError, ValueError):
            normalized[key] = 0
    return normalized


def _validate_topic_payload(
    payload: dict,
    niche: str,
    provider: str,
    model: str,
    *,
    bullet_limit: int = 5,
    minimum_bullets: int = 4,
) -> dict:
    topics = payload.get("topics")
    if not isinstance(topics, list) or not topics:
        raise RuntimeError("Content generator returned no topics.")
    first_topic = topics[0]
    if not isinstance(first_topic, dict):
        raise RuntimeError("Content generator returned an invalid topic shape.")

    title = truncate_text(" ".join(str(first_topic.get("title", "")).split()), 110)
    intro = truncate_text(" ".join(str(first_topic.get("intro", "")).split()), 180)
    cta = truncate_text(" ".join(str(first_topic.get("cta", "")).split()), 180)
    category = truncate_text(" ".join(str(first_topic.get("category", "")).split()), 80)
    topic_formula = truncate_text(" ".join(str(first_topic.get("topic_formula", "")).split()), 120)
    bullets = _normalize_bullets(first_topic.get("bullets", []), limit=bullet_limit)
    if not title or not intro or not cta or len(bullets) < minimum_bullets:
        raise RuntimeError("Content generator returned incomplete topic content.")
    if niche == str(ContentNiche.DARK_CURIOSITY):
        category = _normalize_dark_curiosity_category(category)

    visuals = _normalize_visuals(first_topic.get("visuals", []), expected_count=len(bullets) + 2)
    pixabay_keywords = _expand_pixabay_keywords(
        _normalize_pixabay_keywords(first_topic.get("pixabay_keywords", []), limit=20),
        title=title,
        category=category,
        topic_formula=topic_formula,
        intro=intro,
        bullets=bullets,
        visuals=visuals,
        limit=20,
    )
    viral_scores = _normalize_viral_scores(first_topic.get("viral_scores", {}))
    if niche == str(ContentNiche.DARK_CURIOSITY):
        if len(pixabay_keywords) < 12:
            raise RuntimeError("Dark Curiosity generator returned too little media search context.")
        if min(viral_scores.values()) < 8:
            raise RuntimeError("Dark Curiosity generator returned a topic below the minimum viral score threshold.")
    return {
        "category": category,
        "topic_formula": topic_formula,
        "title": title,
        "intro": intro,
        "bullets": bullets,
        "cta": cta,
        "hashtags": _normalize_hashtags(first_topic.get("hashtags", [])),
        "asset_packs": _normalize_asset_packs(first_topic.get("asset_packs", [])),
        "visuals": visuals,
        "pixabay_keywords": pixabay_keywords,
        "viral_scores": viral_scores,
        "provider": provider,
        "model": model,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "niche": niche,
    }


def _is_recent_topic_duplicate(niche: str, title: str, intro: str, bullets: list[str]) -> bool:
    candidate_title = _normalize_similarity_text(title)
    if candidate_title and candidate_title in {
        _normalize_similarity_text(item) for item in _recently_used_titles(None, limit=60)
    }:
        return True

    candidate_brief = " ".join([title, intro, *bullets])
    for topic in ViralTopic.objects.order_by("-created_at")[:60]:
        topic_text = " ".join([topic.title, topic.hook, topic.script])
        if _topic_similarity(candidate_brief, topic_text) >= 0.7:
            return True
    return False


def build_ai_topic(niche: str) -> ViralTopic:
    niche = niche if niche in {choice.value for choice in ContentNiche} else str(ContentNiche.DARK_CURIOSITY)
    attempts: list[str] = []
    for attempt in range(6):
        raw_payload, provider, model = _generate_topic_payload(niche)
        payload = _validate_topic_payload(raw_payload, niche, provider, model)
        if _is_recent_topic_duplicate(niche, payload["title"], payload["intro"], payload["bullets"]):
            attempts.append(payload["title"])
            continue

        script_lines = [payload["intro"], *payload["bullets"], payload["cta"]]
        script = "\n".join(script_lines)
        scene_plan = build_scene_plan(payload["intro"], payload["bullets"], payload["cta"], visuals=payload["visuals"])
        duration_seconds = estimate_duration_seconds(script, scene_plan)
        if duration_seconds < 35 or duration_seconds > 50:
            attempts.append(f"{payload['title']} ({duration_seconds}s)")
            continue
        content_signature = stable_hash([niche, payload["title"].strip().lower(), " ".join(script.lower().split())])
        return ViralTopic.objects.create(
            niche=niche,
            title=payload["title"],
            hook=payload["intro"],
            script=script,
            scene_plan=scene_plan,
            seo_title=f'{payload["title"]} | {getattr(settings, "CHANNEL_BRAND_NAME", "DarkBrainScroll")}',
            description=script,
            hashtags=payload["hashtags"] or _default_hashtags_for_niche(niche),
            source_notes=[
                f"provider:{payload['provider']}",
                f"model:{payload['model']}",
                f"generated-at:{payload['generated_at']}",
                f"estimated-duration:{duration_seconds}",
                f"content-signature:{content_signature}",
                f"category:{payload['category']}",
                f"topic-formula:{payload['topic_formula']}",
                f"viral-score-curiosity:{payload['viral_scores']['curiosity']}",
                f"viral-score-shock:{payload['viral_scores']['shock']}",
                f"viral-score-retention:{payload['viral_scores']['retention']}",
                f"viral-score-shareability:{payload['viral_scores']['shareability']}",
                *[f"asset-pack:{pack}" for pack in payload["asset_packs"]],
                *[f"pixabay-keyword:{keyword}" for keyword in payload["pixabay_keywords"]],
            ],
            is_trending=False,
        )
    attempted_titles = ", ".join(attempts[:6]) or "none"
    raise RuntimeError(f"Topic generator kept returning repeated ideas for niche '{niche}'. Attempts: {attempted_titles}")


def build_brainrot_video_topic() -> ViralTopic:
    return build_ai_topic(str(ContentNiche.DARK_CURIOSITY))


def build_longform_topic(niche: str) -> ViralTopic:
    niche = niche if niche in {choice.value for choice in ContentNiche} else str(ContentNiche.DARK_CURIOSITY)
    prompt = _longform_topic_prompt(niche)
    attempts: list[str] = []
    for _ in range(6):
        raw_payload, provider, model = _generate_custom_topic_payload_with_system_prompt(
            prompt,
            LONGFORM_JSON_ONLY_SYSTEM_PROMPT,
        )
        payload = _validate_topic_payload(
            raw_payload,
            niche,
            provider,
            model,
            bullet_limit=18,
            minimum_bullets=12,
        )
        if _is_recent_topic_duplicate(niche, payload["title"], payload["intro"], payload["bullets"]):
            attempts.append(payload["title"])
            continue

        script_lines = [payload["intro"], *payload["bullets"], payload["cta"]]
        script = "\n".join(script_lines)
        scene_plan = build_scene_plan(payload["intro"], payload["bullets"], payload["cta"], visuals=payload["visuals"])
        duration_seconds = estimate_longform_duration_seconds(script, scene_plan)
        minimum = max(120, int(getattr(settings, "LONGFORM_MIN_DURATION_SECONDS", 180)))
        maximum = max(minimum, int(getattr(settings, "LONGFORM_MAX_DURATION_SECONDS", 300)))
        if duration_seconds < minimum or duration_seconds > maximum:
            attempts.append(f"{payload['title']} ({duration_seconds}s)")
            continue
        content_signature = stable_hash([niche, payload["title"].strip().lower(), " ".join(script.lower().split())])
        return ViralTopic.objects.create(
            niche=niche,
            title=payload["title"],
            hook=payload["intro"],
            script=script,
            scene_plan=scene_plan,
            seo_title=f'{payload["title"]} | {getattr(settings, "CHANNEL_BRAND_NAME", "DarkBrainScroll")}',
            description=script,
            hashtags=payload["hashtags"] or _default_hashtags_for_niche(niche, longform=True),
            source_notes=[
                f"provider:{payload['provider']}",
                f"model:{payload['model']}",
                f"generated-at:{payload['generated_at']}",
                f"estimated-duration:{duration_seconds}",
                f"content-signature:{content_signature}",
                "content-format:longform",
                "render-mode:video-montage",
                f"category:{payload['category']}",
                f"topic-formula:{payload['topic_formula']}",
                f"viral-score-curiosity:{payload['viral_scores']['curiosity']}",
                f"viral-score-shock:{payload['viral_scores']['shock']}",
                f"viral-score-retention:{payload['viral_scores']['retention']}",
                f"viral-score-shareability:{payload['viral_scores']['shareability']}",
                *[f"asset-pack:{pack}" for pack in payload["asset_packs"]],
                *[f"pixabay-keyword:{keyword}" for keyword in payload["pixabay_keywords"]],
                *[f"video-search:{keyword} documentary footage" for keyword in payload["pixabay_keywords"][:8]],
            ],
            is_trending=False,
        )
    attempted_titles = ", ".join(attempts[:6]) or "none"
    raise RuntimeError(
        f"Long-form topic generator kept returning repeated or invalid ideas for niche '{niche}'. Attempts: {attempted_titles}"
    )
