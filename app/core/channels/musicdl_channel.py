"""musicdl channel.

musicdl's netease client resolves a whole result list (metadata + download URL) per
query, which is slow but produces the richest candidate data. It is kept as the
default first channel because the user prefers a spread of requests over hammering
one endpoint.
"""
from __future__ import annotations

import logging
import tempfile
from typing import Any, Sequence

from .base import Candidate

log = logging.getLogger(__name__)


class MusicdlChannel:
    name = "musicdl"

    def __init__(self, cookie: str | None = None, *, page_size: int = 1, size: int = 1):
        self._cookie = cookie
        self._page_size = page_size
        self._size = size
        self._client = None
        self._error: str | None = None

    def _ensure(self):
        if self._client is not None:
            return self._client
        try:
            from musicdl.modules.sources import NeteaseMusicClient
        except ImportError as exc:  # pragma: no cover - dependency issue
            self._error = f"musicdl 未安装: {exc}"
            raise RuntimeError(self._error) from exc
        client = NeteaseMusicClient()
        client.search_size_per_page = self._page_size
        client.search_size_per_source = self._size
        client.disable_print = True
        client.max_retries = 1
        if self._cookie:
            client.default_cookies = self._cookie
        self._client = client
        return client

    def available(self) -> bool:
        return self._error is None

    def resolve(self, track: Any, quality: str) -> Sequence[Candidate]:
        try:
            client = self._ensure()
        except RuntimeError:
            return []
        title = track["title"] or ""
        artist = track["artist"] or ""
        keyword = f"{title} {artist}".strip()
        try:
            # musicdl writes search_results.pkl under client.work_dir; point it at a
            # throw-away directory so nothing appears next to the program.
            with tempfile.TemporaryDirectory(prefix="nv-musicdl-") as work:
                client.work_dir = work
                results = client.search(keyword=keyword)
        except Exception as exc:  # network / parser problems are ordinary failures
            log.warning("musicdl 搜索失败 %s: %s", keyword, exc)
            return []

        out: list[Candidate] = []
        for item in results or []:
            out.append(Candidate(
                channel=self.name,
                source="wy",
                url=getattr(item, "download_url", None),
                quality=quality,
                title=getattr(item, "song_name", "") or "",
                artist=getattr(item, "singers", "") or "",
                album=getattr(item, "album", "") or "",
                duration_ms=_ms_from_duration(getattr(item, "duration", None)),
                ext=(getattr(item, "ext", None) or None),
                size_bytes=getattr(item, "file_size_bytes", None),
                song_id=_as_int(getattr(item, "identifier", None)),
                match_basis="metadata",
                raw={"source": getattr(item, "source", None)},
            ))
        return out


def _ms_from_duration(value: Any) -> int | None:
    """musicdl exposes "00:03:33"; convert back to milliseconds."""
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        seconds = 0
        for part in value.split(":"):
            seconds = seconds * 60 + int(part)
    except ValueError:
        return None
    return seconds * 1000


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
