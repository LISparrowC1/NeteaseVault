"""Pull the cloud liked list into the local database.

Ordering follows the cloud response exactly; the per-track `at` value is stored so
that a re-like (which changes ordering and time) overwrites the old record instead
of creating a duplicate.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core import states
from ..core.netease import NeteaseClient
from ..db.store import Store, now_iso


@dataclass
class SyncReport:
    playlist_id: int
    playlist_name: str
    total: int
    added: int
    removed: int
    invalid: int
    elapsed_ms: int
    added_titles: list[str] = field(default_factory=list)
    removed_titles: list[str] = field(default_factory=list)

    def as_line(self) -> str:
        return (f"同步完成：{self.playlist_name} 共 {self.total} 首，"
                f"新增 {self.added}，云端移除 {self.removed}，失效 {self.invalid}，"
                f"耗时 {self.elapsed_ms} ms")

    def diff_lines(self, limit: int = 12) -> list[str]:
        lines = []
        for title in self.added_titles[:limit]:
            lines.append(f"+ {title}")
        for title in self.removed_titles[:limit]:
            lines.append(f"- {title}")
        return lines


def _quality_level(privilege: dict[str, Any]) -> str | None:
    return privilege.get("maxBrLevel") or None


def _is_playable(privilege: dict[str, Any]) -> bool:
    st = privilege.get("st")
    return st == 0


def sync_liked(client: NeteaseClient, store: Store, *, playlist_id: int | None = None) -> SyncReport:
    started = time.monotonic()
    run_id = store.start_sync_run()

    profile = client.account()
    uid = int(profile["userId"])
    pid = playlist_id or client.liked_playlist_id(uid)

    summary = client.playlist_summary(pid)
    name = summary.get("name") or "我喜欢的音乐"

    entries = client.playlist_track_ids(pid)
    details = client.songs_detail([e["id"] for e in entries])
    detail_by_id = {int(s["id"]): s for s in details}

    before = store.existing_track_ids()
    added = 0
    invalid = 0
    added_titles: list[str] = []

    with store.tx():
        for index, entry in enumerate(entries):
            song = detail_by_id.get(entry["id"])
            if song is None:
                store.log("sync.missing_detail", song_id=entry["id"],
                          detail={"reason": "详情接口未返回该歌曲"})
                continue
            privilege = song.get("_privilege") or {}
            playable = _is_playable(privilege)
            if not playable:
                invalid += 1

            record = {
                "song_id": int(entry["id"]),
                "order_index": index,
                "add_time": entry.get("at"),
                "title": song.get("name"),
                "artist": "、".join(a.get("name", "") for a in (song.get("ar") or [])) or None,
                "album": (song.get("al") or {}).get("name"),
                "duration_ms": song.get("dt"),
                "cloud_max_quality": _quality_level(privilege),
                "cover_url": (song.get("al") or {}).get("picUrl"),
                "cloud_playable": 1 if playable else 0,
            }
            if store.upsert_track(record):
                added += 1
                added_titles.append(f"{record['title']} - {record['artist'] or ''}")

    current_ids = {e["id"] for e in entries}
    # Only a song that was in the playlist last time can have been removed; local-only
    # rows and already-removed rows must not be reported again on every sync.
    was_present = {sid for sid, row in before.items() if row["cloud_present"]}
    gone = [sid for sid in was_present if sid not in current_ids]
    removed_titles = [f"{before[sid]['title']} - {before[sid]['artist'] or ''}" for sid in gone[:20]]
    store.mark_removed(gone)

    store.upsert_playlist(pid, name, now_iso())
    elapsed = int((time.monotonic() - started) * 1000)
    store.finish_sync_run(run_id, total=len(entries), added=added, removed=len(gone), invalid=invalid)
    store.log("sync.done", detail={"playlist_id": pid, "total": len(entries),
                                   "added": added, "removed": len(gone), "invalid": invalid})

    return SyncReport(pid, name, len(entries), added, len(gone), invalid, elapsed,
                      added_titles, removed_titles)
