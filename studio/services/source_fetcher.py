from __future__ import annotations

from pathlib import Path
import textwrap
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

import requests
from django.conf import settings

from studio.models import MediaAsset, VideoProject
from .utils import media_dir, safe_unlink, slugify_text


SLIDE_BACKGROUNDS = [
    ("#1E293B", "#0F172A"),
    ("#0F766E", "#042F2E"),
    ("#7C2D12", "#431407"),
    ("#4C1D95", "#1E1B4B"),
    ("#9A3412", "#431407"),
]
USER_AGENT = "DarkBrainScrollBot/1.0"
NICHE_QUERY_HINTS = {
    "facts": ["science laboratory", "brain scan", "space galaxy", "microscope research"],
    "tech": ["technology ai", "computer code", "cyber interface", "robotics lab"],
    "money": ["money finance", "stock market", "saving cash", "wallet closeup"],
    "motivation": ["athlete training", "sunrise running", "focus work", "success mindset"],
    "reddit": ["person reading phone", "night room", "anonymous story", "dramatic portrait"],
}
NICHE_PROVIDER_ORDER = {
    "animals": ("pexels", "pixabay", "wikimedia"),
    "motivation": ("pexels", "pixabay", "wikimedia"),
    "celebrity": ("wikimedia", "pexels", "pixabay"),
    "crime": ("wikimedia", "pexels", "pixabay"),
    "history": ("wikimedia", "pexels", "pixabay"),
    "mythology": ("wikimedia", "pexels", "pixabay"),
    "space": ("wikimedia", "pexels", "pixabay"),
    "body": ("wikimedia", "pexels", "pixabay"),
    "facts": ("wikimedia", "pexels", "pixabay"),
}
DEFAULT_PROVIDER_ORDER = ("pexels", "pixabay", "wikimedia")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "can", "do", "does", "for", "from", "has",
    "have", "if", "in", "into", "is", "it", "its", "like", "more", "of", "on", "or", "so", "than", "that", "the",
    "their", "them", "they", "this", "to", "up", "was", "were", "with", "you", "your",
}
PLACEHOLDER_ONLY_MARKERS = {"follow ", "subscribe", "like and follow", "for more facts"}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = [
        "DejaVuSans-Bold.ttf",
        "arial.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]
    for candidate in font_candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_gradient(image: Image.Image, top_color: str, bottom_color: str) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for y in range(height):
        mix = y / max(height - 1, 1)
        start = tuple(int(top_color[i : i + 2], 16) for i in (1, 3, 5))
        end = tuple(int(bottom_color[i : i + 2], 16) for i in (1, 3, 5))
        color = tuple(int(start[i] * (1 - mix) + end[i] * mix) for i in range(3))
        draw.line((0, y, width, y), fill=color)


def _create_scene_slide(project: VideoProject, scene: dict, index: int, output_path: Path) -> None:
    image = Image.new("RGB", (project.target_width, project.target_height), color="#101010")
    top_color, bottom_color = SLIDE_BACKGROUNDS[index % len(SLIDE_BACKGROUNDS)]
    _draw_gradient(image, top_color, bottom_color)
    draw = ImageDraw.Draw(image)

    hook_font = _load_font(54)
    body_font = _load_font(74)
    footer_font = _load_font(36)

    hook = project.topic.hook[:80]
    body = scene.get("text", "").strip()
    wrapped_body = "\n".join(textwrap.wrap(body, width=20)) or "Stay tuned"

    draw.rounded_rectangle((70, 90, project.target_width - 70, 230), radius=36, fill=(255, 255, 255, 28), outline="#F8FAFC", width=3)
    draw.text((110, 125), hook, font=hook_font, fill="#F8FAFC")

    body_box = (72, 360, project.target_width - 72, project.target_height - 310)
    draw.rounded_rectangle(body_box, radius=46, fill=(15, 23, 42, 150), outline="#FDE68A", width=4)
    draw.multiline_text((120, 430), wrapped_body, font=body_font, fill="#FFFFFF", spacing=18, align="left")

    footer = f"{getattr(settings, 'CHANNEL_BRAND_NAME', 'DarkBrainScroll')}  |  AI Shorts"
    draw.text((110, project.target_height - 180), footer, font=footer_font, fill="#E2E8F0")

    accent_y = project.target_height - 120
    draw.rounded_rectangle((110, accent_y, project.target_width - 110, accent_y + 18), radius=18, fill="#F97316")

    image.save(output_path, quality=92)


def _scene_keyword_phrase(text: str, max_words: int = 6) -> str:
    words = []
    for raw_word in text.replace("-", " ").split():
        cleaned = "".join(char for char in raw_word.lower() if char.isalnum())
        if not cleaned or cleaned in STOPWORDS or len(cleaned) < 3:
            continue
        words.append(cleaned)
    unique_words: list[str] = []
    for word in words:
        if word not in unique_words:
            unique_words.append(word)
    return " ".join(unique_words[:max_words])


def _scene_prefers_placeholder(scene: dict) -> bool:
    text = (scene.get("text") or "").strip().lower()
    return any(marker in text for marker in PLACEHOLDER_ONLY_MARKERS) or "darkbrainscroll" in text


def _topic_keyword_phrase(project: VideoProject, max_words: int = 8) -> str:
    script = " ".join(str(scene.get("text") or "") for scene in list(project.topic.scene_plan or [])[:4])
    return _scene_keyword_phrase(f"{project.topic.title} {project.niche} {script}", max_words=max_words)


def _asset_pack_terms(project: VideoProject, limit: int = 2) -> list[str]:
    terms: list[str] = []
    for note in project.topic.source_notes or []:
        if not str(note).startswith("asset-pack:"):
            continue
        value = str(note).split(":", 1)[1].strip()
        if value and value.lower() not in {item.lower() for item in terms}:
            terms.append(value)
        if len(terms) >= limit:
            break
    return terms


def _build_scene_queries(project: VideoProject, scene: dict) -> list[str]:
    scene_text = scene.get("text", "").strip()
    visual_hint = str(scene.get("visual_hint") or "").strip()
    keyword_phrase = _scene_keyword_phrase(scene_text)
    topic_keywords = _topic_keyword_phrase(project)
    asset_packs = _asset_pack_terms(project)
    candidates = [
        visual_hint,
        f"{visual_hint} realistic photo" if visual_hint else "",
        f"{visual_hint} vertical photo" if visual_hint else "",
        keyword_phrase,
        f"{keyword_phrase} realistic photo" if keyword_phrase else "",
        f"{keyword_phrase} documentary photo" if keyword_phrase else "",
        f"{project.topic.title} photo" if len(project.topic.title.split()) <= 8 else "",
        f"{project.niche} {topic_keywords}" if topic_keywords else "",
        f"{project.niche} {keyword_phrase} photo" if keyword_phrase else "",
        scene_text,
        f"{keyword_phrase} wildlife photo" if project.niche == "animals" and keyword_phrase else "",
        f"{keyword_phrase} historical photo" if project.niche in ["facts", "mythology", "celebrity"] and keyword_phrase else "",
        f"{keyword_phrase} science illustration" if project.niche in ["facts", "space", "body", "tech"] and keyword_phrase else "",
        f"{project.niche} {keyword_phrase}" if keyword_phrase else "",
    ]
    for pack in asset_packs:
        candidates.append(f"{pack} {keyword_phrase}".strip())
        candidates.append(f"{pack} {visual_hint}".strip())
    candidates.extend(NICHE_QUERY_HINTS.get(project.niche, []))
    queries: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = " ".join(item.split()).strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            queries.append(normalized)
    return queries


def _download_image(url: str, output_path: Path) -> bool:
    response = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    image = Image.open(BytesIO(response.content)).convert("RGB")
    image.save(output_path, format="JPEG", quality=92)
    return True


def _pexels_candidates(query: str, per_page: int = 6) -> list[dict]:
    token = getattr(settings, "PEXELS_API_KEY", "")
    if not token:
        return []
    response = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": token, "User-Agent": USER_AGENT},
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("photos", [])


def _pixabay_candidates(query: str, per_page: int = 6) -> list[dict]:
    token = getattr(settings, "PIXABAY_API_KEY", "")
    if not token:
        return []
    response = requests.get(
        "https://pixabay.com/api/",
        params={
            "key": token,
            "q": query,
            "image_type": "photo",
            "orientation": "vertical",
            "per_page": per_page,
            "safesearch": "true",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("hits", [])


def _wikimedia_candidates(query: str, per_page: int = 6) -> list[dict]:
    response = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrsearch": query,
            "gsrlimit": per_page,
            "prop": "imageinfo",
            "iiprop": "url|user",
            "iiurlwidth": 1200,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    return list(pages.values())


def _provider_search_order(project: VideoProject) -> tuple[str, ...]:
    return NICHE_PROVIDER_ORDER.get(project.niche, DEFAULT_PROVIDER_ORDER)


def _query_budget() -> tuple[int, int]:
    max_queries = max(1, int(getattr(settings, "STOCK_MEDIA_MAX_SEARCH_QUERIES_PER_SCENE", 2)))
    per_page = max(1, min(8, int(getattr(settings, "STOCK_MEDIA_MAX_CANDIDATES_PER_QUERY", 4))))
    return max_queries, per_page


def _resolve_pexels_image(query: str, output_path: Path, used_urls: set[str], per_page: int) -> dict | None:
    try:
        photos = _pexels_candidates(query, per_page=per_page)
    except requests.RequestException:
        return None
    for photo in photos:
        candidate_url = (
            photo.get("src", {}).get("portrait")
            or photo.get("src", {}).get("large2x")
            or photo.get("src", {}).get("large")
        )
        if not candidate_url or candidate_url in used_urls:
            continue
        _download_image(candidate_url, output_path)
        used_urls.add(candidate_url)
        return {
            "provider": "pexels",
            "credit": photo.get("photographer", ""),
            "source_url": photo.get("url", ""),
            "remote_asset_url": candidate_url,
            "query": query,
        }
    return None


def _resolve_pixabay_image(query: str, output_path: Path, used_urls: set[str], per_page: int) -> dict | None:
    try:
        photos = _pixabay_candidates(query, per_page=per_page)
    except requests.RequestException:
        return None
    for photo in photos:
        candidate_url = photo.get("largeImageURL") or photo.get("webformatURL")
        if not candidate_url or candidate_url in used_urls:
            continue
        _download_image(candidate_url, output_path)
        used_urls.add(candidate_url)
        return {
            "provider": "pixabay",
            "credit": photo.get("user", ""),
            "source_url": photo.get("pageURL", ""),
            "remote_asset_url": candidate_url,
            "query": query,
        }
    return None


def _resolve_wikimedia_image(query: str, output_path: Path, used_urls: set[str], per_page: int) -> dict | None:
    try:
        photos = _wikimedia_candidates(query, per_page=per_page)
    except requests.RequestException:
        return None
    for photo in photos:
        image_info = (photo.get("imageinfo") or [{}])[0]
        candidate_url = image_info.get("thumburl") or image_info.get("url")
        if not candidate_url or candidate_url in used_urls:
            continue
        _download_image(candidate_url, output_path)
        used_urls.add(candidate_url)
        return {
            "provider": "wikimedia",
            "credit": image_info.get("user", ""),
            "source_url": image_info.get("descriptionurl", ""),
            "remote_asset_url": candidate_url,
            "query": query,
        }
    return None


def _resolve_stock_image(project: VideoProject, query: str, output_path: Path, used_urls: set[str], per_page: int) -> dict | None:
    resolver_map = {
        "pexels": _resolve_pexels_image,
        "pixabay": _resolve_pixabay_image,
        "wikimedia": _resolve_wikimedia_image,
    }
    for provider in _provider_search_order(project):
        result = resolver_map[provider](query, output_path, used_urls, per_page)
        if result:
            return result
    return None


def _clear_existing_assets(project: VideoProject) -> None:
    for asset in project.assets.all():
        if asset.local_path:
            safe_unlink(asset.local_path)
    project.assets.all().delete()


def fetch_placeholder_assets(project: VideoProject) -> list[MediaAsset]:
    scene_dir = media_dir("projects", str(project.id), "assets")
    assets: list[MediaAsset] = []
    for index, scene in enumerate(project.topic.scene_plan):
        prompt = slugify_text(scene.get("text", f"scene-{index+1}"))
        placeholder = Path(scene_dir / f"{index+1:02d}-{prompt}.png")
        _create_scene_slide(project, scene, index, placeholder)
        assets.append(
            MediaAsset.objects.create(
                project=project,
                asset_type="image",
                local_path=str(placeholder),
                metadata={"placeholder": True, "query": prompt, "scene": scene},
                sort_order=index,
            )
        )
    return assets


def fetch_scene_assets(project: VideoProject, replace_existing: bool = False) -> list[MediaAsset]:
    if replace_existing:
        _clear_existing_assets(project)

    if project.assets.exists():
        return list(project.assets.order_by("sort_order"))

    if not getattr(settings, "USE_STOCK_MEDIA", False):
        return fetch_placeholder_assets(project)

    scene_dir = media_dir("projects", str(project.id), "assets")
    assets: list[MediaAsset] = []
    used_urls: set[str] = set()
    max_queries_per_scene, per_page = _query_budget()
    min_real_target = max(1, int(getattr(settings, "STOCK_MEDIA_MIN_REAL_SCENE_TARGET", 3)))
    real_assets_created = 0

    for index, scene in enumerate(project.topic.scene_plan):
        prompt = slugify_text(scene.get("text", f"scene-{index+1}"))
        output_path = Path(scene_dir / f"{index+1:02d}-{prompt}.jpg")
        stock_result = None
        can_try_real_image = not _scene_prefers_placeholder(scene) or real_assets_created < min_real_target
        if can_try_real_image:
            for query in _build_scene_queries(project, scene)[:max_queries_per_scene]:
                try:
                    stock_result = _resolve_stock_image(project, query, output_path, used_urls, per_page)
                except requests.RequestException:
                    continue
                if stock_result:
                    break

        if not stock_result:
            output_path = Path(scene_dir / f"{index+1:02d}-{prompt}.png")
            _create_scene_slide(project, scene, index, output_path)
            asset = MediaAsset.objects.create(
                project=project,
                asset_type="image",
                local_path=str(output_path),
                metadata={"placeholder": True, "query": prompt, "scene": scene},
                sort_order=index,
            )
        else:
            real_assets_created += 1
            asset = MediaAsset.objects.create(
                project=project,
                asset_type="image",
                local_path=str(output_path),
                source_url=stock_result["source_url"],
                credit=stock_result["credit"],
                metadata={
                    "placeholder": False,
                    "provider": stock_result["provider"],
                    "remote_asset_url": stock_result["remote_asset_url"],
                    "query": stock_result["query"],
                    "scene": scene,
                },
                sort_order=index,
            )
        assets.append(asset)

    return assets
