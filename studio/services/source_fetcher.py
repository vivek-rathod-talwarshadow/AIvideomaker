from __future__ import annotations

from pathlib import Path
import json

import requests
from django.conf import settings

from studio.models import MediaAsset, VideoProject
from .utils import media_dir, slugify_text


def fetch_placeholder_assets(project: VideoProject) -> list[MediaAsset]:
    scene_dir = media_dir("projects", str(project.id), "assets")
    assets: list[MediaAsset] = []
    for index, scene in enumerate(project.topic.scene_plan):
        prompt = slugify_text(scene.get("text", f"scene-{index+1}"))
        placeholder = Path(scene_dir / f"{index+1:02d}-{prompt}.json")
        placeholder.write_text(json.dumps({"scene": scene, "note": "replace with Pexels/Pixabay fetch result"}), encoding="utf-8")
        assets.append(
            MediaAsset.objects.create(
                project=project,
                asset_type="image",
                local_path=str(placeholder),
                metadata={"placeholder": True, "query": prompt},
                sort_order=index,
            )
        )
    return assets


def fetch_pexels_images(query: str, per_page: int = 5) -> list[dict]:
    token = getattr(settings, "PEXELS_API_KEY", "")
    if not token:
        return []

    response = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": token},
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("photos", [])
