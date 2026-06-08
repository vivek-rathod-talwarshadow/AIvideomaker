from __future__ import annotations

from pathlib import Path
import hashlib
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
    "dark-curiosity": ["abandoned place", "mysterious ruins", "dark ocean", "space signal", "ancient artifact"],
    "facts": ["science laboratory", "brain scan", "space galaxy", "microscope research"],
    "tech": ["technology ai", "computer code", "cyber interface", "robotics lab"],
    "money": ["money finance", "stock market", "saving cash", "wallet closeup"],
    "motivation": ["athlete training", "sunrise running", "focus work", "success mindset"],
    "reddit": ["person reading phone", "night room", "anonymous story", "dramatic portrait"],
    "psychology": ["dramatic portrait", "couple tension", "texting phone", "social interaction"],
    "celebrity": ["red carpet event", "paparazzi crowd", "stage performance", "fashion portrait"],
    "glam": ["fashion portrait", "dance pose", "cosplay photoshoot", "party lights portrait"],
    "theory": ["mysterious silhouette", "glitch screen", "conspiracy board", "late night computer"],
    "crime": ["detective board", "city alley night", "interrogation room", "police evidence wall"],
}
NICHE_PROVIDER_ORDER = {
    "dark-curiosity": ("pexels", "pixabay", "wikimedia"),
    "animals": ("pexels", "pixabay", "wikimedia"),
    "motivation": ("pexels", "pixabay", "wikimedia"),
    "glam": ("pexels", "pixabay", "wikimedia"),
    "celebrity": ("pexels", "wikimedia", "pixabay"),
    "crime": ("wikimedia", "pexels", "pixabay"),
    "history": ("wikimedia", "pexels", "pixabay"),
    "mythology": ("wikimedia", "pexels", "pixabay"),
    "space": ("wikimedia", "pexels", "pixabay"),
    "body": ("wikimedia", "pexels", "pixabay"),
    "facts": ("wikimedia", "pexels", "pixabay"),
    "reddit": ("pexels", "pixabay", "wikimedia"),
    "psychology": ("pexels", "pixabay", "wikimedia"),
    "theory": ("pexels", "pixabay", "wikimedia"),
}
DEFAULT_PROVIDER_ORDER = ("pexels", "pixabay", "wikimedia")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "can", "do", "does", "for", "from", "has",
    "have", "if", "in", "into", "is", "it", "its", "like", "more", "of", "on", "or", "so", "than", "that", "the",
    "their", "them", "they", "this", "to", "up", "was", "were", "with", "you", "your",
}
PLACEHOLDER_ONLY_MARKERS = {"follow ", "subscribe", "like and follow", "for more facts"}
GENERIC_FALLBACK_IMAGE_SOURCES = (
    "https://picsum.photos/seed/{seed}/900/1600",
    "https://loremflickr.com/900/1600/{query_slug}",
)
BRAINROT_VIDEO_QUERY_HINTS = [
    "glamorous adult woman fashion portrait video",
    "fashion model woman city walk video",
    "anime style cosplay woman video",
    "japanese woman street style video",
    "korean woman fashion lifestyle video",
    "latina woman lifestyle video",
    "cute adult woman smiling lifestyle video",
    "beautiful woman fashion portrait video",
    "fashion woman outfit transition video",
    "model woman photoshoot video",
    "glamour woman luxury fashion video",
    "stylish woman street fashion video",
    "trendy woman influencer lifestyle video",
    "influencer woman daily life video",
    "beach lifestyle woman video",
    "summer vacation woman video",
    "swimwear model woman beach video",
    "fitness woman workout video",
    "gym woman portrait workout video",
    "yoga woman wellness video",
    "sporty woman lifestyle video",
    "dancing woman festival video",
    "smiling woman portrait video",
    "happy woman city lifestyle video",
    "luxury lifestyle woman video",
    "rich lifestyle woman video",
    "travel woman aesthetic video",
    "adventure travel woman video",
    "office woman business lifestyle video",
    "businesswoman office portrait video",
    "woman entrepreneur workspace video",
    "boss woman city office video",
    "party woman nightlife video",
    "festival fashion woman video",
    "concert crowd woman video",
    "nightlife woman city video",
    "city woman street style video",
    "urban woman lifestyle video",
    "nature woman lifestyle video",
    "hiking woman adventure video",
    "camping woman outdoor video",
    "photographer woman creative video",
    "artist woman studio video",
    "music lover woman lifestyle video",
    "gamer woman setup video",
    "streamer woman desk video",
    "cosplay woman portrait video",
    "manga style cosplay woman video",
    "kawaii fashion woman video",
    "harajuku fashion woman video",
    "thai woman lifestyle video",
    "vietnamese woman lifestyle video",
    "filipino woman lifestyle video",
    "indonesian woman lifestyle video",
    "malaysian woman lifestyle video",
    "singaporean woman city lifestyle video",
    "indian woman fashion lifestyle video",
    "pakistani woman fashion video",
    "bangladeshi woman lifestyle video",
    "nepali woman lifestyle video",
    "sri lankan woman travel video",
    "brazilian woman beach lifestyle video",
    "mexican woman lifestyle video",
    "colombian woman city lifestyle video",
    "argentine woman fashion video",
    "spanish woman city fashion video",
    "italian woman luxury fashion video",
    "french woman chic fashion video",
    "german woman urban lifestyle video",
    "british woman city style video",
    "irish woman lifestyle video",
    "swedish woman minimalist fashion video",
    "norwegian woman travel lifestyle video",
    "danish woman scandinavian style video",
    "finnish woman lifestyle video",
    "dutch woman city style video",
    "belgian woman chic lifestyle video",
    "greek woman vacation video",
    "turkish woman fashion lifestyle video",
    "russian woman city fashion video",
    "ukrainian woman street style video",
    "polish woman lifestyle video",
    "czech woman city lifestyle video",
    "romanian woman fashion video",
    "middle eastern woman luxury lifestyle video",
    "arab woman fashion lifestyle video",
    "lebanese woman chic lifestyle video",
    "persian woman elegant fashion video",
    "african woman fashion lifestyle video",
    "nigerian woman luxury lifestyle video",
    "ethiopian woman lifestyle video",
    "south african woman travel video",
    "american woman city lifestyle video",
    "canadian woman casual fashion video",
    "australian woman beach lifestyle video",
    "new zealand woman adventure video",
    "blonde woman fashion portrait video",
    "brunette woman city fashion video",
    "redhead woman lifestyle video",
    "curly hair woman beauty video",
    "long hair woman fashion video",
    "short hair woman chic video",
    "ponytail woman sporty video",
    "runway model woman video",
    "street style woman fashion video",
    "aesthetic woman lifestyle video",
    "minimalist woman lifestyle video",
    "vintage fashion woman video",
    "retro fashion woman video",
    "y2k fashion woman video",
    "e girl fashion woman video",
    "soft aesthetic woman video",
    "cottagecore woman lifestyle video",
    "fairycore fashion woman video",
    "dark feminine woman lifestyle video",
    "elegant woman luxury video",
    "classy woman city lifestyle video",
    "chic woman fashion video",
    "luxury fashion woman video",
    "designer fashion woman video",
    "makeup woman beauty video",
    "beauty woman skincare video",
    "skincare routine woman video",
    "wellness woman lifestyle video",
    "healthy lifestyle woman video",
    "coffee shop woman lifestyle video",
    "cafe woman aesthetic video",
    "book lover woman cafe video",
    "romantic woman dreamy lifestyle video",
    "cute smile woman portrait video",
    "selfie woman influencer video",
    "vlogger woman lifestyle video",
    "short form creator woman video",
    "content creator woman setup video",
    "dance creator woman video",
    "lifestyle influencer woman video",
    "travel influencer woman video",
    "fashion influencer woman video",
    "beauty influencer woman video",
    "fitness influencer woman video",
    "tropical vacation woman video",
    "island resort woman video",
    "vacation woman sunset video",
    "poolside woman luxury video",
    "ocean lifestyle woman video",
    "surf woman beach video",
    "skater woman street video",
    "biker woman city video",
    "car lifestyle woman video",
    "supercar woman luxury video",
    "motorcycle woman lifestyle video",
    "tennis woman sports video",
    "volleyball woman beach sports video",
    "basketball woman athletic video",
    "soccer woman athletic video",
    "runner woman fitness video",
    "athletic woman portrait video",
    "pilates woman wellness video",
    "dance fitness woman video",
    "cheerful woman lifestyle video",
    "confident woman city video",
    "independent woman lifestyle video",
    "modern woman fashion video",
    "trendsetter woman street style video",
    "fashionista woman city video",
    "luxury traveler woman video",
    "backpacker woman travel video",
    "adventure traveler woman video",
    "festival fashion woman video",
    "streetwear woman city video",
    "casual fashion woman video",
    "formal fashion woman video",
    "evening dress woman video",
    "summer fashion woman video",
    "winter fashion woman video",
    "spring fashion woman video",
    "autumn fashion woman video",
    "glam woman luxury video",
    "celebrity look woman fashion video",
    "actress style woman video",
    "pop star style woman video",
    "idol style woman dance video",
    "k pop style woman video",
    "j pop style woman video",
    "digital creator woman video",
    "ai influencer woman video",
    "virtual model woman video",
    "cinematic woman portrait video",
    "viral style woman lifestyle video",
    "trending fashion woman video",
    "aesthetic model woman video",
    "lifestyle model woman video",
    "fashion photoshoot woman video",
]
GENERIC_FALLBACK_VIDEO_SOURCES = (
    "https://samplelib.com/mp4/sample-5s.mp4",
    "https://samplelib.com/mp4/sample-10s.mp4",
    "https://samplelib.com/mp4/sample-15s.mp4",
    "https://samplelib.com/mp4/sample-20s.mp4",
    "https://samplelib.com/mp4/sample-30s.mp4",
)
REGULAR_VIDEO_QUERY_HINTS = {
    "dark-curiosity": ["abandoned building footage", "ancient ruins footage", "deep ocean footage", "space signal animation", "mysterious forest footage"],
    "facts": ["science laboratory footage", "space documentary footage", "microscope research footage", "brain scan footage"],
    "tech": ["ai interface footage", "computer code screen footage", "robotics lab footage", "technology office footage"],
    "money": ["luxury city lifestyle footage", "stock market screen footage", "cash counting footage", "business office footage"],
    "motivation": ["athlete training footage", "sunrise running footage", "focus work footage", "success office footage"],
    "reddit": ["person texting phone footage", "dramatic hallway footage", "couple argument silhouette footage", "late night room footage"],
    "psychology": ["social interaction footage", "couple tension footage", "woman thinking portrait footage", "texting behavior footage"],
    "celebrity": ["red carpet footage", "stage performance footage", "paparazzi crowd footage", "fashion event footage"],
    "glam": BRAINROT_VIDEO_QUERY_HINTS,
    "theory": ["mysterious silhouette footage", "glitch screen footage", "late night computer footage", "dark city night footage"],
    "crime": ["detective board footage", "city alley night footage", "police evidence wall footage", "interrogation room footage"],
}
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

    footer = getattr(settings, "CHANNEL_BRAND_NAME", "DarkBrainScroll")
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
    pixabay_keywords = _topic_note_terms(project, "pixabay-keyword:", limit=6)
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
    candidates.extend(pixabay_keywords)
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


def _download_binary(url: str, output_path: Path) -> bool:
    response = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT}, stream=True)
    response.raise_for_status()
    with output_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)
    return output_path.exists() and output_path.stat().st_size > 0


def _configured_token(value: str) -> str:
    token = str(value or "").strip()
    if not token or token.startswith("<") or token.lower() in {"secret", "your_api_key_here", "changeme"}:
        return ""
    return token


def _pexels_candidates(query: str, per_page: int = 6) -> list[dict]:
    token = _configured_token(getattr(settings, "PEXELS_API_KEY", ""))
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
    token = _configured_token(getattr(settings, "PIXABAY_API_KEY", ""))
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


def _is_landscape_project(project: VideoProject) -> bool:
    return int(project.target_width or 0) > int(project.target_height or 0)


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


def _resolve_generic_fallback_image(query: str, output_path: Path, used_urls: set[str]) -> dict | None:
    query_slug = slugify_text(query or "viral-scene")
    for template in GENERIC_FALLBACK_IMAGE_SOURCES:
        candidate_url = template.format(seed=query_slug, query_slug=query_slug.replace("-", ","))
        if candidate_url in used_urls:
            continue
        try:
            _download_image(candidate_url, output_path)
        except requests.RequestException:
            continue
        used_urls.add(candidate_url)
        return {
            "provider": "generic-fallback",
            "credit": "",
            "source_url": candidate_url,
            "remote_asset_url": candidate_url,
            "query": query,
        }
    return None


def _project_render_mode(project: VideoProject) -> str:
    for note in project.topic.source_notes or []:
        if str(note).startswith("render-mode:"):
            return str(note).split(":", 1)[1].strip().lower()
    return ""


def _is_brainrot_video_project(project: VideoProject) -> bool:
    return _project_render_mode(project) == "brainrot-video"


def _video_search_terms(project: VideoProject, limit: int = 8) -> list[str]:
    return _topic_note_terms(project, "video-search:", limit=limit)


def _topic_note_terms(project: VideoProject, prefix: str, limit: int = 8) -> list[str]:
    terms: list[str] = []
    for note in project.topic.source_notes or []:
        if not str(note).startswith(prefix):
            continue
        value = str(note).split(":", 1)[1].strip()
        if value and value.lower() not in {item.lower() for item in terms}:
            terms.append(value)
        if len(terms) >= limit:
            break
    return terms


def _recent_remote_video_urls(limit: int = 500) -> set[str]:
    urls: set[str] = set()
    for asset in MediaAsset.objects.filter(asset_type="video").order_by("-created_at")[:limit]:
        remote_url = str((asset.metadata or {}).get("remote_asset_url") or "").strip()
        if remote_url:
            urls.add(remote_url)
    return urls


def _build_brainrot_scene_queries(project: VideoProject, scene: dict) -> list[str]:
    seed_text = f"{project.id}|{scene.get('text', '')}|{scene.get('visual_hint', '')}"
    ordered = sorted(
        BRAINROT_VIDEO_QUERY_HINTS,
        key=lambda item: hashlib.sha1(f"{seed_text}|{item}".encode("utf-8")).hexdigest(),
    )
    return ordered


def _build_regular_video_scene_queries(project: VideoProject, scene: dict) -> list[str]:
    visual_hint = str(scene.get("visual_hint") or "").strip()
    scene_text = str(scene.get("text") or "").strip()
    keyword_phrase = _scene_keyword_phrase(scene_text, max_words=8)
    pixabay_keywords = _topic_note_terms(project, "pixabay-keyword:", limit=8)
    orientation_hint = "horizontal cinematic footage" if _is_landscape_project(project) else "vertical stock video"
    candidates = [
        visual_hint,
        f"{visual_hint} footage" if visual_hint else "",
        f"{visual_hint} cinematic video" if visual_hint else "",
        f"{visual_hint} horizontal cinematic footage" if visual_hint and _is_landscape_project(project) else "",
        keyword_phrase,
        f"{keyword_phrase} footage" if keyword_phrase else "",
        f"{keyword_phrase} landscape documentary footage" if keyword_phrase and _is_landscape_project(project) else "",
        f"{project.niche} {keyword_phrase} footage" if keyword_phrase else "",
        f"{project.topic.title} documentary footage" if len(project.topic.title.split()) <= 8 else "",
        *pixabay_keywords,
        *_video_search_terms(project, limit=6),
        *REGULAR_VIDEO_QUERY_HINTS.get(project.niche, []),
        orientation_hint,
        "documentary footage",
    ]
    queries: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = " ".join(item.split()).strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            queries.append(normalized)
    return queries


def _pexels_video_candidates(query: str, per_page: int = 6, orientation: str = "portrait") -> list[dict]:
    token = _configured_token(getattr(settings, "PEXELS_API_KEY", ""))
    if not token:
        return []
    query_variants = [
        {"query": query, "per_page": per_page, "orientation": orientation, "size": "medium"},
        {"query": query, "per_page": per_page, "orientation": orientation},
        {"query": query, "per_page": per_page},
    ]
    for params in query_variants:
        response = requests.get(
            "https://api.pexels.com/v1/videos/search",
            headers={"Authorization": token, "User-Agent": USER_AGENT},
            params=params,
            timeout=30,
        )
        if response.status_code == 401:
            return []
        response.raise_for_status()
        videos = response.json().get("videos", [])
        if videos:
            return videos
    return []


def _pixabay_video_candidates(query: str, per_page: int = 6) -> list[dict]:
    token = _configured_token(getattr(settings, "PIXABAY_API_KEY", ""))
    if not token:
        return []
    query_variants = [
        {
            "key": token,
            "q": query,
            "video_type": "all",
            "per_page": per_page,
            "safesearch": "true",
            "category": "people",
        },
        {
            "key": token,
            "q": query,
            "video_type": "all",
            "per_page": per_page,
            "safesearch": "true",
        },
    ]
    for params in query_variants:
        response = requests.get(
            "https://pixabay.com/api/videos/",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        if response.status_code in {400, 401, 403}:
            continue
        response.raise_for_status()
        hits = response.json().get("hits", [])
        if hits:
            return hits
    return []


def _pick_pexels_video_file(video: dict, prefer_landscape: bool = False) -> dict | None:
    files = list(video.get("video_files") or [])
    oriented_files = [
        item
        for item in files
        if (int(item.get("width") or 0) >= int(item.get("height") or 0)) == prefer_landscape
    ]
    ranked = oriented_files or files
    target_height = 1080 if prefer_landscape else 1280
    ranked.sort(key=lambda item: (abs((item.get("height") or 0) - target_height), -(item.get("width") or 0)))
    return ranked[0] if ranked else None


def _pick_pixabay_video_file(video: dict) -> dict | None:
    variants = video.get("videos") or {}
    candidates = [variants.get("medium"), variants.get("small"), variants.get("tiny"), variants.get("large")]
    for item in candidates:
        if item and item.get("url"):
            return item
    return None


def _resolve_pexels_video(
    query: str,
    output_path: Path,
    used_urls: set[str],
    per_page: int,
    prefer_landscape: bool = False,
) -> dict | None:
    try:
        videos = _pexels_video_candidates(
            query,
            per_page=per_page,
            orientation="landscape" if prefer_landscape else "portrait",
        )
    except requests.RequestException:
        return None
    ranked_videos = sorted(
        videos,
        key=lambda video: hashlib.sha1(f"{query}|{video.get('id','')}".encode("utf-8")).hexdigest(),
    )
    for video in ranked_videos:
        file_info = _pick_pexels_video_file(video, prefer_landscape=prefer_landscape)
        candidate_url = file_info.get("link") if file_info else ""
        if not candidate_url or candidate_url in used_urls:
            continue
        _download_binary(candidate_url, output_path)
        used_urls.add(candidate_url)
        return {
            "provider": "pexels",
            "credit": video.get("user", {}).get("name", ""),
            "source_url": video.get("url", ""),
            "remote_asset_url": candidate_url,
            "query": query,
        }
    return None


def _resolve_pixabay_video(query: str, output_path: Path, used_urls: set[str], per_page: int) -> dict | None:
    try:
        videos = _pixabay_video_candidates(query, per_page=per_page)
    except requests.RequestException:
        return None
    ranked_videos = sorted(
        videos,
        key=lambda video: hashlib.sha1(f"{query}|{video.get('id','')}".encode("utf-8")).hexdigest(),
    )
    for video in ranked_videos:
        file_info = _pick_pixabay_video_file(video)
        candidate_url = file_info.get("url") if file_info else ""
        if not candidate_url or candidate_url in used_urls:
            continue
        _download_binary(candidate_url, output_path)
        used_urls.add(candidate_url)
        return {
            "provider": "pixabay",
            "credit": video.get("user", ""),
            "source_url": video.get("pageURL", ""),
            "remote_asset_url": candidate_url,
            "query": query,
        }
    return None


def _resolve_stock_video(
    project: VideoProject,
    query: str,
    output_path: Path,
    used_urls: set[str],
    per_page: int,
) -> dict | None:
    prefer_landscape = _is_landscape_project(project)
    result = _resolve_pexels_video(
        query,
        output_path,
        used_urls,
        per_page,
        prefer_landscape=prefer_landscape,
    )
    if result:
        return result
    result = _resolve_pixabay_video(query, output_path, used_urls, per_page)
    if result:
        return result
    return None


def _resolve_generic_fallback_video(output_path: Path, used_urls: set[str], seed: str) -> dict | None:
    ordered_sources = sorted(
        GENERIC_FALLBACK_VIDEO_SOURCES,
        key=lambda item: hashlib.sha1(f"{seed}|{item}".encode("utf-8")).hexdigest(),
    )
    for candidate_url in ordered_sources:
        if candidate_url in used_urls:
            continue
        try:
            _download_binary(candidate_url, output_path)
        except requests.RequestException:
            continue
        used_urls.add(candidate_url)
        return {
            "provider": "generic-fallback-video",
            "credit": "samplelib.com",
            "source_url": "https://samplelib.com/sample-mp4.html",
            "remote_asset_url": candidate_url,
            "query": seed,
        }
    return None


def fetch_video_scene_assets(project: VideoProject, replace_existing: bool = False) -> list[MediaAsset]:
    if replace_existing:
        _clear_existing_assets(project)

    existing_assets = project.assets.filter(asset_type="video")
    if existing_assets.exists():
        return list(existing_assets.order_by("sort_order"))

    scene_dir = media_dir("projects", str(project.id), "assets")
    assets: list[MediaAsset] = []
    used_urls: set[str] = _recent_remote_video_urls() if _is_brainrot_video_project(project) else set()
    max_queries_per_scene, per_page = _query_budget()
    is_brainrot = _is_brainrot_video_project(project)

    for index, scene in enumerate(project.topic.scene_plan):
        prompt = slugify_text(scene.get("text", f"scene-{index+1}"))
        output_path = Path(scene_dir / f"{index+1:02d}-{prompt}.mp4")
        stock_result = None
        query_builder = _build_brainrot_scene_queries if is_brainrot else _build_regular_video_scene_queries
        query_limit = max(max_queries_per_scene + (4 if is_brainrot else 2), 5)
        for query in query_builder(project, scene)[:query_limit]:
            try:
                stock_result = _resolve_stock_video(project, query, output_path, used_urls, per_page)
            except requests.RequestException:
                continue
            if stock_result:
                break
        if not stock_result:
            broad_queries = BRAINROT_VIDEO_QUERY_HINTS if is_brainrot else REGULAR_VIDEO_QUERY_HINTS.get(project.niche, [])
            for query in broad_queries:
                try:
                    stock_result = _resolve_stock_video(project, query, output_path, used_urls, per_page)
                except requests.RequestException:
                    continue
                if stock_result:
                    break
        if not stock_result:
            if not is_brainrot:
                fallback_seed = str(scene.get("visual_hint") or scene.get("text") or prompt)
                stock_result = _resolve_generic_fallback_video(output_path, used_urls, fallback_seed)
        if not stock_result:
            raise RuntimeError(f"Could not find stock video footage for scene {index + 1}.")

        asset = MediaAsset.objects.create(
            project=project,
            asset_type="video",
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
    return fetch_video_scene_assets(project, replace_existing=replace_existing)
