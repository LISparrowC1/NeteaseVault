"""Album-art cache.

Covers are never written into audio files; they are fetched from the cloud cover URL
and cached under `data/cache/covers`, keyed by a hash of the URL.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from ..config import app_root


def cache_dir() -> Path:
    path = app_root() / "data" / "cache" / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def cached_path(url: str) -> Path:
    return cache_dir() / _key(url)


def load(url: str) -> bytes | None:
    path = cached_path(url)
    if path.exists():
        try:
            return path.read_bytes()
        except OSError:
            return None
    return None


def fetch(url: str, timeout: int = 15) -> bytes | None:
    """Return image bytes, downloading and caching on first use."""
    cached = load(url)
    if cached:
        return cached
    try:
        import requests

        response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code != 200 or not response.content:
            return None
        path = cached_path(url)
        path.write_bytes(response.content)
        return response.content
    except Exception:
        return None


def cache_size() -> tuple[int, int]:
    """(file count, bytes) of the cover cache."""
    root = cache_dir()
    files = [p for p in root.glob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def clear() -> int:
    """Drop cached covers and any leftover staging data. Returns bytes freed."""
    freed = 0
    for directory in (cache_dir(), app_root() / "data" / "staging"):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file():
                try:
                    freed += path.stat().st_size
                except OSError:
                    pass
        shutil.rmtree(directory, ignore_errors=True)
    cache_dir()
    return freed
