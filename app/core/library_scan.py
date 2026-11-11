"""Reconcile the library folder with the database.

A file's association with a cloud track is *derived from disk on every sync*, never
stored as independent truth. That keeps three things consistent:

* clearing sync info really empties every status (nothing is remembered)
* re-syncing re-links the same files instead of creating duplicates
* a file with no cloud counterpart is shown as 本地

Files are named "<title> - <artist>.<ext>", so the association is a name match.
"""
from __future__ import annotations

from pathlib import Path

from .audio import probe
from .normalize import normalize

AUDIO_SUFFIXES = {".flac", ".mp3", ".m4a", ".wav", ".ape", ".ogg", ".dsf", ".aiff"}


def split_stem(stem: str) -> tuple[str, str]:
    if " - " in stem:
        title, artist = stem.rsplit(" - ", 1)
        return title.strip(), artist.strip()
    return stem.strip(), ""


def reconcile_local(store, library: Path) -> dict[str, int]:
    """Rebuild the local/cloud association. Returns counters for the UI."""
    stats = {"linked": 0, "orphan": 0, "missing": 0, "merged": 0}
    if not library.exists():
        return stats

    rows = store.all_tracks()
    cloud_index: dict[tuple[str, str], object] = {}
    for row in rows:
        if row["cloud_present"]:
            cloud_index.setdefault(
                (normalize(row["title"]), normalize(row["artist"])), row)

    seen_rel: set[str] = set()
    adopted_ids: set[int] = set()

    for path in sorted(library.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        rel = path.relative_to(library).as_posix()
        seen_rel.add(rel)
        title, artist = split_stem(path.stem)
        key = (normalize(title), normalize(artist))
        cloud = cloud_index.get(key)

        if cloud is not None and int(cloud["song_id"]) not in adopted_ids:
            adopted_ids.add(int(cloud["song_id"]))
            if cloud["local_rel_path"] != rel or cloud["local_state"] != "downloaded":
                store.attach_local(int(cloud["song_id"]), rel_path=rel,
                                   fmt=path.suffix.lstrip("."), quality="lossless")
            stats["linked"] += 1
            continue

        # No cloud counterpart: keep one local-only row per file.
        existing = store.find_by_rel_path(rel)
        if existing is None:
            duration = None
            try:
                duration = probe(path).duration_ms
            except Exception:
                pass
            store.register_local_file(rel_path=rel, title=title, artist=artist, album="",
                                      duration_ms=duration, fmt=path.suffix.lstrip("."))
            stats["orphan"] += 1
        elif not existing["cloud_present"]:
            stats["orphan"] += 1

    # Forget rows whose file disappeared...
    for row in rows:
        rel = row["local_rel_path"]
        if not rel:
            continue
        if rel not in seen_rel:
            store.forget_local(int(row["song_id"]))
            stats["missing"] += 1

    # ...and drop local-only rows now covered by a cloud row. This is what caused
    # the same song to appear twice (correct place + bottom of the list).
    adopted_keys = {(normalize(row["title"]), normalize(row["artist"]))
                    for row in rows if int(row["song_id"]) in adopted_ids}
    stale = [int(row["song_id"]) for row in rows
             if row["local_only"] and (normalize(row["title"]), normalize(row["artist"])) in adopted_keys]
    if stale:
        store.delete_tracks(stale)
        stats["merged"] = len(stale)
    return stats
