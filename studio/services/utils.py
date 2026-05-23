from __future__ import annotations

from pathlib import Path
import hashlib
import os
import re
import shutil
import time
from typing import Iterable

from django.conf import settings


def ensure_dir(path: str | Path) -> Path:
    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return path_obj


def media_dir(*parts: str) -> Path:
    return ensure_dir(Path(settings.MEDIA_ROOT).joinpath(*parts))


def slugify_text(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value[:80] or "item"


def truncate_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def stable_hash(parts: Iterable[str]) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def safe_unlink(path: str | Path, retries: int = 6, delay_seconds: float = 0.5) -> bool:
    path_obj = Path(path)
    for attempt in range(retries):
        try:
            os.remove(path_obj)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt == retries - 1:
                return False
            time.sleep(delay_seconds)
    return False


def safe_rmtree(path: str | Path, retries: int = 6, delay_seconds: float = 0.5) -> bool:
    path_obj = Path(path)
    for attempt in range(retries):
        shutil.rmtree(path_obj, ignore_errors=True)
        if not path_obj.exists():
            return True
        if attempt == retries - 1:
            return False
        time.sleep(delay_seconds)
    return not path_obj.exists()
