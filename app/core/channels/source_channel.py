"""LX custom-source channel.

Source scripts can only turn platform-native ids into a URL, so for a netease track
this path is still exact: we hand over the netease song id.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from .base import Candidate

log = logging.getLogger(__name__)


def music_info(track: Any) -> dict[str, Any]:
    duration_ms = track["duration_ms"] or 0
    return {
        "songmid": str(track["song_id"]),
        "copyrightId": str(track["song_id"]),
        "hash": str(track["song_id"]),
        "name": track["title"] or "",
        "singer": track["artist"] or "",
        "albumName": track["album"] or "",
        "albumId": "",
        "interval": int(round(duration_ms / 1000)),
        "duration": duration_ms,
        "source": "wy",
        "id": str(track["song_id"]),
        "_types": {},
        "typeUrl": {},
    }


class SourceChannel:
    name = "source"

    def __init__(self, engine, scripts: list[str] | None = None, *, allow_degraded: bool = False):
        self._engine = engine
        self._scripts = scripts
        self._allow_degraded = allow_degraded
        self._loaded: list[dict[str, Any]] | None = None
        self._error: str | None = None

    def available(self) -> bool:
        return self._error is None and self._engine is not None

    def _script_list(self) -> list[dict[str, Any]]:
        if self._loaded is not None:
            return self._loaded
        try:
            scripts = self._engine.call("scripts")
        except Exception as exc:
            self._error = str(exc)
            log.warning("引擎不可用: %s", exc)
            return []
        wanted = set(self._scripts) if self._scripts else None
        usable = []
        for item in scripts:
            if item.get("error"):
                continue
            if not item.get("ready"):
                continue
            sources = item.get("sources") or {}
            if "wy" not in sources:
                continue
            if wanted is not None and item["file"] not in wanted:
                continue
            usable.append(item)
        if self._scripts:
            order = {name: index for index, name in enumerate(self._scripts)}
            usable.sort(key=lambda item: order.get(item["file"], 999))
        self._loaded = usable
        return usable

    def resolve(self, track: Any, quality: str) -> Sequence[Candidate]:
        scripts = self._script_list()
        if not scripts:
            return []
        info = music_info(track)
        out: list[Candidate] = []
        for item in scripts:
            wy = item["sources"]["wy"]
            qualities = wy.get("qualitys") or []
            if not qualities:
                continue
            tier = quality if quality in qualities else ("320k" if "320k" in qualities else qualities[0])
            try:
                result = self._engine.call("resolve", {
                    "file": item["file"], "source": "wy",
                    "quality": tier, "musicInfo": info,
                }, timeout=40)
            except Exception as exc:
                log.info("源 %s 解析失败: %s", item.get("name") or item["file"], exc)
                continue
            url = (result or {}).get("url")
            if not url:
                continue
            out.append(Candidate(
                channel=self.name,
                source="wy",
                url=url,
                quality=tier,
                title=track["title"] or "",
                artist=track["artist"] or "",
                album=track["album"] or "",
                duration_ms=track["duration_ms"],
                song_id=int(track["song_id"]),
                match_basis="song_id",
                raw={"script": item["file"], "script_name": item.get("name")},
            ))
            if len(out) >= 3:
                break
        return out
