"""Download pipeline: resolve -> match -> fetch -> verify -> clean -> publish."""
from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import requests

from ..db.store import Store, now_iso
from . import states
from .audio import AudioProbeError, classify_lossless, detect_format, probe, spectrum_delta
from .channels.base import Candidate
from .clean import clean_file, strip_lyric_header
from .match import match_candidate

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


@dataclass
class TrackResult:
    song_id: int
    status: str               # downloaded / review / failed
    channel: str | None = None
    quality: str | None = None
    path: str | None = None
    message: str = ""
    elapsed_ms: int = 0
    candidates: list[Candidate] = field(default_factory=list)


def safe_name(title: str, artist: str) -> str:
    base = f"{title} - {artist}" if artist else (title or "unknown")
    base = _ILLEGAL.sub("_", base).strip().strip(".")
    return base[:120] or "unknown"


def _unique_path(directory: Path, stem: str, ext: str) -> Path:
    candidate = directory / f"{stem}.{ext}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({index}).{ext}"
        index += 1
    return candidate


def pick_candidate(track: Any, candidates: Sequence[Candidate]) -> tuple[Candidate | None, str]:
    """Return (candidate, basis). Id matches beat metadata matches."""
    with_url = [c for c in candidates if c.url]
    id_hits = [c for c in with_url if c.song_id and c.song_id == int(track["song_id"])]
    if len(id_hits) == 1:
        return id_hits[0], "song_id"
    as_track = {"title": track["title"], "artist": track["artist"],
                "album": track["album"], "duration_ms": track["duration_ms"]}
    passing = []
    for candidate in with_url:
        result = match_candidate(as_track, {
            "title": candidate.title, "artist": candidate.artist,
            "album": candidate.album, "duration_ms": candidate.duration_ms,
        })
        if result.passed:
            passing.append(candidate)
    if len(passing) == 1:
        return passing[0], "metadata"
    return None, ""


def download_to(candidate: Candidate, target: Path, timeout: int = 300,
                pause_event=None, cancel_event=None, on_progress=None) -> int:
    partial = target.with_suffix(target.suffix + ".part")
    written = 0
    with requests.get(candidate.url, stream=True, timeout=timeout,
                      headers={"User-Agent": UA, "Referer": "https://music.163.com/"}) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        with partial.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if _cancelled(cancel_event):
                    raise RuntimeError("已取消")
                _wait_while_paused(pause_event, cancel_event)
                if chunk:
                    handle.write(chunk)
                    written += len(chunk)
                    if on_progress is not None and total:
                        on_progress(min(1.0, written / total))
    partial.replace(target)
    return written


def _target_quality(track: Any) -> str:
    cloud = (track["cloud_max_quality"] or "").lower()
    return "hires" if cloud == "hires" else "lossless"


def download_chosen(track: Any, candidate: Candidate, store: Store, *, library: Path,
                    staging: Path, lyric_fetcher=None, expected_lossless: bool = True,
                    pause_event=None, cancel_event=None, on_progress=None
                    ) -> tuple[Path | None, str]:
    """Fetch a specific candidate and publish it. Returns (path, message)."""
    song_id = int(track["song_id"])
    channel_dir = staging / str(song_id)
    channel_dir.mkdir(parents=True, exist_ok=True)
    target = channel_dir / "source.bin"
    try:
        download_to(candidate, target, pause_event=pause_event,
                    cancel_event=cancel_event, on_progress=on_progress)
    except Exception as exc:
        store.log("download.fetch_error", song_id=song_id,
                  detail={"channel": candidate.channel, "error": str(exc)})
        shutil.rmtree(channel_dir, ignore_errors=True)
        return None, f"下载失败: {exc}"

    try:
        fmt = detect_format(target) or (candidate.ext or "").lower() or None
        if not fmt:
            raise AudioProbeError("下载到的内容不是可识别的音频")
        ext = fmt
        target = target.rename(channel_dir / f"source.{ext}")
        info = probe(target)
    except Exception as exc:
        store.log("download.probe_error", song_id=song_id,
                  detail={"channel": candidate.channel, "error": str(exc)})
        shutil.rmtree(channel_dir, ignore_errors=True)
        return None, f"文件不可识别: {exc}"

    if expected_lossless and not info.is_lossless_container:
        store.log("download.not_lossless", song_id=song_id,
                  detail={"channel": candidate.channel, "got": info.fmt})
        shutil.rmtree(channel_dir, ignore_errors=True)
        return None, f"拿到的是 {info.fmt}，不是无损"

    lyrics = ""
    if lyric_fetcher is not None:
        try:
            lyrics = strip_lyric_header(lyric_fetcher(song_id))
        except Exception:
            lyrics = ""

    delta = spectrum_delta(target) if info.is_lossless_container else None
    verdict, reason = classify_lossless(info, delta)
    if verdict == "fake":
        store.log("download.fake_lossless", song_id=song_id,
                  detail={"channel": candidate.channel, "reason": reason})
        shutil.rmtree(channel_dir, ignore_errors=True)
        return None, reason

    tags = {
        "TITLE": track["title"] or "",
        "ARTIST": track["artist"] or "",
        "ALBUM": track["album"] or "",
        "LYRICS": lyrics,
    }
    report = clean_file(target, tags)
    if not report.ok:
        store.log("clean.failed", song_id=song_id, detail={"problems": report.problems})
        shutil.rmtree(channel_dir, ignore_errors=True)
        return None, "清洗复检失败: " + "; ".join(report.problems)

    final_path = _unique_path(library, safe_name(track["title"] or "", track["artist"] or ""), ext)
    shutil.move(str(target), str(final_path))
    shutil.rmtree(channel_dir, ignore_errors=True)
    store.update_local(song_id, rel_path=str(final_path.relative_to(library)),
                       fmt=info.fmt, quality=candidate.quality,
                       duration_ms=info.duration_ms)
    store.log("download.done", song_id=song_id,
              detail={"channel": candidate.channel, "quality": candidate.quality,
                      "spectrum_delta": delta, "verdict": verdict, "reason": reason,
                      "clean": report.after})
    return final_path, reason


def process_track(track: Any, channels: Sequence[Any], store: Store, *,
                  library: Path, staging: Path, lyric_fetcher=None,
                  pause_event=None, cancel_event=None, on_progress=None) -> TrackResult:
    started = time.monotonic()
    song_id = int(track["song_id"])
    quality = _target_quality(track)
    staging.mkdir(parents=True, exist_ok=True)
    library.mkdir(parents=True, exist_ok=True)

    all_candidates: list[Candidate] = []
    for channel in channels:
        if cancel_event is not None and cancel_event.is_set():
            break
        if not channel.available():
            continue
        try:
            candidates = list(channel.resolve(track, quality))
        except Exception as exc:
            store.log("download.resolve_error", song_id=song_id,
                      detail={"channel": channel.name, "error": str(exc)})
            continue
        all_candidates.extend(candidates)
        chosen, basis = pick_candidate(track, candidates)
        if chosen is None:
            continue

        path, message = download_chosen(
            track, chosen, store, library=library, staging=staging,
            lyric_fetcher=lyric_fetcher, expected_lossless=quality in ("lossless", "hires"),
            pause_event=pause_event, cancel_event=cancel_event, on_progress=on_progress)
        if path is None:
            if cancel_event is not None and cancel_event.is_set():
                break
            continue
        elapsed = int((time.monotonic() - started) * 1000)
        return TrackResult(song_id, "downloaded", chosen.channel, chosen.quality,
                           str(path), message, elapsed, all_candidates)

    elapsed = int((time.monotonic() - started) * 1000)
    store.set_local_state(song_id, states.PENDING_REVIEW)
    store.add_approval(song_id, "没有满足条件的候选",
                       [c.as_record() for c in all_candidates])
    store.log("download.needs_review", song_id=song_id,
              detail={"candidates": [c.as_record() for c in all_candidates]}, elapsed_ms=elapsed)
    return TrackResult(song_id, "review", None, quality, None,
                       f"没有可用候选（{len(all_candidates)} 个）", elapsed, all_candidates)


def _cancelled(event) -> bool:
    return event is not None and event.is_set()


def _wait_while_paused(pause_event, cancel_event) -> None:
    if pause_event is None:
        return
    while not pause_event.is_set():
        if _cancelled(cancel_event):
            raise RuntimeError("已取消")
        time.sleep(0.15)
