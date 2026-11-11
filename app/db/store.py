"""SQLite persistence. Thin on purpose: SQL here, decisions in the callers.

The track table splits the cloud axis (present / playable) from the local axis
(local_state). Lists are derived from those columns via ``states.LIST_SQL`` so a song
leaving and re-entering the liked list keeps its downloaded state.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..config import bundle_root
from ..core import states

SCHEMA = bundle_root() / "app" / "db" / "schema.sql"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        if not SCHEMA.exists():
            raise FileNotFoundError(f"缺少数据库结构文件: {SCHEMA}")
        self._conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        self._migrate()
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_track_cloud ON track(cloud_present)")
        self._conn.commit()

    # -- migration --------------------------------------------------------

    def _columns(self, table: str) -> set[str]:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] for row in rows}

    def _migrate(self) -> None:
        """Upgrade a database created by the old single-`state` model."""
        columns = self._columns("track")
        if "cloud_present" not in columns:
            self._conn.execute("ALTER TABLE track ADD COLUMN cloud_present INTEGER NOT NULL DEFAULT 1")
        if "local_state" not in columns:
            self._conn.execute("ALTER TABLE track ADD COLUMN local_state TEXT NOT NULL DEFAULT 'none'")
        if "local_only" not in columns:
            self._conn.execute("ALTER TABLE track ADD COLUMN local_only INTEGER NOT NULL DEFAULT 0")
        if "cover_url" not in columns:
            self._conn.execute("ALTER TABLE track ADD COLUMN cover_url TEXT")
        if "state" in columns:
            # Backfill once: the legacy column is the only place the old info lives.
            self._conn.execute(
                "UPDATE track SET local_state = CASE state "
                "  WHEN 'in_library' THEN 'downloaded' "
                "  WHEN 'pending_review' THEN 'pending_review' "
                "  WHEN 'match_failed' THEN 'match_failed' "
                "  ELSE 'none' END "
                "WHERE local_state = 'none' OR local_state IS NULL")
            self._conn.execute(
                "UPDATE track SET cloud_present = 0, removed_at = COALESCE(removed_at, last_seen_at) "
                "WHERE state = 'removed_cloud'")
            # The legacy column is NOT NULL and no longer written; drop it or every
            # insert fails. Recent SQLite supports DROP COLUMN; otherwise rebuild.
            try:
                self._conn.execute("ALTER TABLE track DROP COLUMN state")
            except sqlite3.OperationalError:
                self._rebuild_track_table_without_state()
            self._conn.commit()
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_track_cloud ON track(cloud_present)")
        self._conn.commit()

    def _rebuild_track_table_without_state(self) -> None:
        """Fallback for SQLite builds without DROP COLUMN."""
        self._conn.execute("ALTER TABLE track RENAME TO track_legacy")
        self._conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(track)")]
        joined = ", ".join(columns)
        self._conn.execute(f"INSERT INTO track ({joined}) SELECT {joined} FROM track_legacy")
        self._conn.execute("DROP TABLE track_legacy")

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- meta -------------------------------------------------------------

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def clear_meta(self, key: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM meta WHERE key=?", (key,))

    # -- playlist / sync --------------------------------------------------

    def upsert_playlist(self, playlist_id: int, name: str, synced_at: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO playlist(id, name, last_sync_at) VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, last_sync_at=excluded.last_sync_at",
                (playlist_id, name, synced_at))

    def start_sync_run(self) -> int:
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO sync_run(started_at) VALUES (?)", (now_iso(),))
            return int(cur.lastrowid)

    def finish_sync_run(self, run_id: int, **counts: int) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE sync_run SET finished_at=?, total=?, added=?, removed=?, invalid=? WHERE id=?",
                (now_iso(), counts.get("total", 0), counts.get("added", 0),
                 counts.get("removed", 0), counts.get("invalid", 0), run_id))

    def last_sync_at(self) -> str | None:
        row = self._conn.execute(
            "SELECT MAX(finished_at) AS t FROM sync_run WHERE finished_at IS NOT NULL").fetchone()
        return row["t"] if row and row["t"] else None

    def existing_track_ids(self) -> dict[int, sqlite3.Row]:
        rows = self._conn.execute("SELECT * FROM track").fetchall()
        return {int(row["song_id"]): row for row in rows}

    def upsert_track(self, record: dict[str, Any], *, new_state: str | None = None) -> bool:
        """Insert or refresh cloud-side data. Never touches ``local_state``."""
        existing = self._conn.execute(
            "SELECT song_id FROM track WHERE song_id=?", (record["song_id"],)).fetchone()
        ts = now_iso()
        if existing:
            self._conn.execute(
                """
                UPDATE track SET order_index=?, add_time=?, title=?, artist=?, album=?,
                    duration_ms=?, cloud_max_quality=?, cover_url=?, cloud_playable=?,
                    cloud_present=1, local_only=0, removed_at=NULL, last_seen_at=?
                WHERE song_id=?
                """,
                (record["order_index"], record.get("add_time"), record.get("title"),
                 record.get("artist"), record.get("album"), record.get("duration_ms"),
                 record.get("cloud_max_quality"), record.get("cover_url"),
                 record.get("cloud_playable", 1), ts, record["song_id"]))
            return False
        self._conn.execute(
            """
            INSERT INTO track(song_id, order_index, add_time, title, artist, album, duration_ms,
                cloud_max_quality, cover_url, cloud_playable, cloud_present, local_state,
                first_seen_at, last_seen_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,1,'none',?,?)
            """,
            (record["song_id"], record["order_index"], record.get("add_time"),
             record.get("title"), record.get("artist"), record.get("album"),
             record.get("duration_ms"), record.get("cloud_max_quality"),
             record.get("cover_url"), record.get("cloud_playable", 1), ts, ts))
        return True

    def mark_removed(self, song_ids: Iterable[int]) -> int:
        ids = list(song_ids)
        if not ids:
            return 0
        ts = now_iso()
        with self.tx() as conn:
            conn.executemany(
                "UPDATE track SET cloud_present=0, removed_at=? "
                "WHERE song_id=? AND cloud_present=1",
                [(ts, int(song_id)) for song_id in ids])
        return len(ids)

    # -- queries ----------------------------------------------------------

    def list_tracks(self, list_key: str = states.LIST_ALL, *, limit: int | None = None) -> list[sqlite3.Row]:
        predicate = states.LIST_SQL.get(list_key, states.LIST_SQL[states.LIST_ALL])
        sql = f"SELECT * FROM track WHERE {predicate} ORDER BY local_only, order_index"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self._conn.execute(sql).fetchall()

    def all_tracks(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM track ORDER BY order_index").fetchall()

    def get_track(self, song_id: int) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM track WHERE song_id=?", (song_id,)).fetchone()

    def counts(self) -> dict[str, int]:
        return {key: len(self.list_tracks(key)) for key in states.LISTS}

    # -- local state ------------------------------------------------------

    def update_local(self, song_id: int, *, rel_path: str, fmt: str, quality: str,
                     duration_ms: int | None, state: str = states.DOWNLOADED) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                UPDATE track SET local_rel_path=?, local_format=?, local_quality=?,
                    local_duration_ms=?, local_state=?
                WHERE song_id=?
                """,
                (rel_path, fmt, quality, duration_ms, state, song_id))

    def set_local_state(self, song_id: int, state: str) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE track SET local_state=? WHERE song_id=?", (state, song_id))

    def forget_local(self, song_id: int, *, state: str = states.NONE) -> None:
        """The file is gone from disk: drop the local record but keep the track."""
        with self.tx() as conn:
            conn.execute(
                "UPDATE track SET local_state=?, local_rel_path=NULL, local_format=NULL, "
                "local_quality=NULL, local_duration_ms=NULL WHERE song_id=?",
                (state, song_id))

    # -- deletion ---------------------------------------------------------

    def delete_tracks(self, song_ids: Iterable[int]) -> int:
        ids = [int(song_id) for song_id in song_ids]
        if not ids:
            return 0
        with self.tx() as conn:
            conn.executemany("DELETE FROM track WHERE song_id=?", [(i,) for i in ids])
            conn.executemany("DELETE FROM approval WHERE song_id=?", [(i,) for i in ids])
        return len(ids)

    def clear_list(self, list_key: str) -> int:
        """Clear one list by acting on the axis that defines it.

        已下载 is a local view: clearing it must only forget the file association,
        never delete the cloud row (the song is still liked).
        """
        rows = self.list_tracks(list_key)
        ids = [int(row["song_id"]) for row in rows]
        if not ids:
            return 0
        if list_key == states.LIST_DOWNLOADED:
            with self.tx() as conn:
                conn.executemany("DELETE FROM track WHERE song_id=? AND local_only=1",
                                 [(i,) for i in ids])
                conn.executemany(
                    "UPDATE track SET local_state='none', local_rel_path=NULL, local_format=NULL, "
                    "local_quality=NULL, local_duration_ms=NULL WHERE song_id=?",
                    [(i,) for i in ids])
            return len(ids)
        if list_key in (states.LIST_REVIEW, states.LIST_FAILED):
            with self.tx() as conn:
                conn.executemany("UPDATE track SET local_state='none' WHERE song_id=?",
                                 [(i,) for i in ids])
            return len(ids)
        return self.delete_tracks(ids)

    def clear_all(self) -> int:
        ids = [int(row["song_id"]) for row in self.all_tracks()]
        with self.tx() as conn:
            conn.execute("DELETE FROM track")
            conn.execute("DELETE FROM approval")
            conn.execute("DELETE FROM playlist")
        return len(ids)

    def clear_sync_data(self) -> int:
        """Forget only what the cloud told us.

        Songs that still have a file keep their local record (that is what 已下载
        shows); songs that were never downloaded disappear. A cloud-side operation
        never erases local state.
        """
        with self.tx() as conn:
            conn.execute(
                "UPDATE track SET local_only=1, cloud_present=0, order_index=0, removed_at=NULL "
                "WHERE local_rel_path IS NOT NULL")
            cur = conn.execute("DELETE FROM track WHERE local_rel_path IS NULL")
            removed = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            conn.execute("DELETE FROM approval WHERE song_id NOT IN (SELECT song_id FROM track)")
            conn.execute("DELETE FROM playlist")
            conn.execute("DELETE FROM sync_run")
        return removed

    def attach_local(self, song_id: int, *, rel_path: str, fmt: str,
                     quality: str | None = None, duration_ms: int | None = None) -> None:
        """Bind a cloud row to its file on disk."""
        with self.tx() as conn:
            conn.execute(
                """
                UPDATE track SET local_rel_path=?, local_format=?, local_quality=?,
                    local_duration_ms=COALESCE(?, local_duration_ms),
                    local_state='downloaded', local_only=0
                WHERE song_id=?
                """,
                (rel_path, fmt, quality, duration_ms, song_id))

    def find_by_rel_path(self, rel_path: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM track WHERE local_rel_path=?", (rel_path,)).fetchone()

    def register_local_file(self, *, rel_path: str, title: str, artist: str, album: str,
                            duration_ms: int | None, quality: str | None = None,
                            fmt: str | None = None) -> int:
        """Create a local-only row for a file that exists but is not in the database."""
        import hashlib

        digest = hashlib.md5(rel_path.encode("utf-8")).hexdigest()[:12]
        song_id = -int(digest, 16)
        ts = now_iso()
        with self.tx() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO track(song_id, order_index, title, artist, album,
                    duration_ms, cloud_playable, cloud_present, local_state, local_only,
                    local_rel_path, local_format, local_quality, local_duration_ms,
                    first_seen_at, last_seen_at)
                VALUES (?,0,?,?,?,?,1,0,'downloaded',1,?,?,?,?,?,?)
                """,
                (song_id, title, artist, album, duration_ms, rel_path, fmt, quality,
                 duration_ms, ts, ts))
        return song_id

    def clear_sync_history(self) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM sync_run")
            conn.execute("DELETE FROM process_log WHERE stage LIKE 'sync.%'")

    # -- logging ----------------------------------------------------------

    def log(self, stage: str, *, song_id: int | None = None, detail: Any = None,
            elapsed_ms: int | None = None) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO process_log(song_id, stage, detail_json, elapsed_ms, created_at) VALUES (?,?,?,?,?)",
                (song_id, stage, json.dumps(detail, ensure_ascii=False) if detail is not None else None,
                 elapsed_ms, now_iso()))

    # -- approvals --------------------------------------------------------

    def add_approval(self, song_id: int, reason: str, candidates: list[dict]) -> int:
        with self.tx() as conn:
            cur = conn.execute(
                "INSERT INTO approval(song_id, reason, candidates_json, decision, created_at) "
                "VALUES (?,?,?,'pending',?)",
                (song_id, reason, json.dumps(candidates, ensure_ascii=False), now_iso()))
            return int(cur.lastrowid)

    def approval_for(self, song_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM approval WHERE song_id=? AND decision='pending' ORDER BY id DESC LIMIT 1",
            (song_id,)).fetchone()

    def decide_approval(self, approval_id: int, decision: str, note: str = "") -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE approval SET decision=?, decided_at=?, note=? WHERE id=?",
                (decision, now_iso(), note, approval_id))

    # -- source scripts ---------------------------------------------------

    def list_scripts(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM source_script ORDER BY priority, id").fetchall()

    def script_state(self) -> dict[str, dict]:
        return {row["file_path"]: dict(row) for row in self.list_scripts()}

    def upsert_script(self, file_path: str, *, name: str = "", version: str = "",
                      enabled: bool = True, priority: int = 0, sources: dict | None = None,
                      note: str = "") -> None:
        with self.tx() as conn:
            existing = conn.execute(
                "SELECT id FROM source_script WHERE file_path=?", (file_path,)).fetchone()
            payload = json.dumps(sources or {}, ensure_ascii=False)
            if existing:
                conn.execute(
                    "UPDATE source_script SET name=?, version=?, sources_json=?, note=? WHERE file_path=?",
                    (name, version, payload, note, file_path))
            else:
                conn.execute(
                    "INSERT INTO source_script(name, version, file_path, enabled, priority, "
                    "sources_json, note) VALUES (?,?,?,?,?,?,?)",
                    (name, version, file_path, 1 if enabled else 0, priority, payload, note))

    def set_script_enabled(self, file_path: str, enabled: bool) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE source_script SET enabled=? WHERE file_path=?",
                         (1 if enabled else 0, file_path))

    def record_health(self, file_path: str, ok: bool, latency_ms: int | None, note: str = "") -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE source_script SET last_check_at=?, last_check_ok=?, "
                "last_latency_ms=?, note=? WHERE file_path=?",
                (now_iso(), 1 if ok else 0, latency_ms, note, file_path))
