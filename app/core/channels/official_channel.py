"""Official channel: resolve by song id.

Because the track already carries its netease id, this path needs no search and is
therefore exact rather than probabilistic. It still obeys the configured chain order,
so it normally runs last.
"""
from __future__ import annotations

from typing import Any, Sequence

from .base import Candidate

QUALITY_LEVEL = {
    "hires": "hires",
    "lossless": "lossless",
    "exhigh": "exhigh",
    "standard": "standard",
}


class OfficialChannel:
    name = "official"

    def __init__(self, client):
        self._client = client

    def available(self) -> bool:
        return self._client is not None

    def resolve(self, track: Any, quality: str) -> Sequence[Candidate]:
        song_id = int(track["song_id"])
        try:
            row = self._client.song_url(song_id, quality)
        except Exception:
            return []
        if not row or not row.get("url"):
            return []
        level = row.get("level") or ""
        return [Candidate(
            channel=self.name,
            source="wy",
            url=row.get("url"),
            quality=quality,
            title=track["title"] or "",
            artist=track["artist"] or "",
            album=track["album"] or "",
            duration_ms=row.get("time") or track["duration_ms"],
            size_bytes=row.get("size"),
            ext=row.get("type"),
            song_id=song_id,
            match_basis="song_id",
            raw={"level": level, "br": row.get("br"), "code": row.get("code")},
        )]
