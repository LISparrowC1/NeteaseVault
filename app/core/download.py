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

from ..db.store import Store
from . import states
from .audio import AudioProbeError, detect_format, probe
from .channels.base import Candidate
from .clean import clean_file, strip_lyric_header
from .match import match_candidate
from .normalize import duration_seconds
from .ratelimit import RateLimiter
from .spectrum import SpectrumError, analyze_file, classify_metrics

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class DownloadCancelled(RuntimeError):
    """Raised inside the fetch loop when the user cancels; not a fetch failure."""


@dataclass
class TrackResult:
    song_id: int
    status: str               # downloaded / review / failed / cancelled
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
    """Return (candidate, basis).  A single matching song_id is authoritative."""
    with_url = [c for c in candidates if c.url]
    id_hits = [c for c in with_url if c.song_id and c.song_id == int(track["song_id"])]
    if len(id_hits) == 1:
        return id_hits[0], "song_id"
    if len(id_hits) > 1:
        return None, ""
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
                pause_event=None, cancel_event=None, on_progress=None,
                rate_limiter: RateLimiter | None = None) -> int:
    if rate_limiter is not None:
        rate_limiter.wait(cancel_event)
    partial = target.with_suffix(target.suffix + ".part")
    written = 0
    with requests.get(candidate.url, stream=True, timeout=timeout,
                      headers={"User-Agent": UA, "Referer": "https://music.163.com/"}) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        with partial.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if _cancelled(cancel_event):
                    raise DownloadCancelled("已取消")
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


def _duration_matches(track: Any, info) -> bool:
    expected = duration_seconds(track["duration_ms"])
    actual = duration_seconds(info.duration_ms)
    return expected is not None and expected == actual


def download_chosen(track: Any, candidate: Candidate, store: Store, *, library: Path,
                    staging: Path, lyric_fetcher=None, expected_lossless: bool = True,
                    pause_event=None, cancel_event=None, on_progress=None,
                    min_bitrate: float = 400.0, manual_bitrate: float = 600.0,
                    retries: int = 2, rate_limiter: RateLimiter | None = None
                    ) -> tuple[Path | None, str]:
    """Fetch a specific candidate and publish it. Returns (path, message).

    ``expected_lossless=False`` is the explicit manual override: a 320K file may be
    accepted after the user confirms it.  Automatic downloads run the spectral gate
    *before* tag cleaning; cleaning is the last step before the atomic move.
    """
    song_id = int(track["song_id"])
    library.mkdir(parents=True, exist_ok=True)
    channel_dir = staging / str(song_id)
    channel_dir.mkdir(parents=True, exist_ok=True)
    target = channel_dir / "source.bin"
    last_error: Exception | None = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            download_to(candidate, target, pause_event=pause_event,
                        cancel_event=cancel_event, on_progress=on_progress,
                        rate_limiter=rate_limiter)
            last_error = None
            break
        except DownloadCancelled:
            shutil.rmtree(channel_dir, ignore_errors=True)
            return None, "已取消"
        except Exception as exc:
            last_error = exc
            target.with_suffix(target.suffix + ".part").unlink(missing_ok=True)
            if _cancelled(cancel_event):
                shutil.rmtree(channel_dir, ignore_errors=True)
                return None, "已取消"
            if attempt < max(0, int(retries)):
                store.log("download.fetch_retry", song_id=song_id,
                          detail={"channel": candidate.channel, "attempt": attempt + 1,
                                  "error": str(exc)})
                time.sleep(min(2.0, 0.4 * (attempt + 1)))
    if last_error is not None:
        store.log("download.fetch_error", song_id=song_id,
                  detail={"channel": candidate.channel, "error": str(last_error)})
        shutil.rmtree(channel_dir, ignore_errors=True)
        return None, f"下载失败: {last_error}"

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

    if not _duration_matches(track, info):
        expected = duration_seconds(track["duration_ms"])
        actual = duration_seconds(info.duration_ms)
        store.log("download.duration_mismatch", song_id=song_id,
                  detail={"channel": candidate.channel, "expected_s": expected,
                          "actual_s": actual, "file_ms": info.duration_ms})
        shutil.rmtree(channel_dir, ignore_errors=True)
        return None, f"时长不符：云端 {expected}s，文件 {actual}s"

    verdict, reason = "manual", "人工接受非无损"
    metrics = None
    if expected_lossless:
        try:
            metrics = analyze_file(target)
            verdict, reason = classify_metrics(
                metrics, bitrate_kbps=info.bitrate_kbps,
                min_bitrate=min_bitrate, manual_bitrate=manual_bitrate)
        except SpectrumError as exc:
            verdict, reason = "unknown", f"频谱无法判定: {exc}"
        except Exception as exc:  # decoding failure must not auto-pass
            verdict, reason = "unknown", f"频谱分析失败: {exc}"
        if verdict == "fake":
            store.log("download.fake_lossless", song_id=song_id,
                      detail={"channel": candidate.channel, "reason": reason,
                              "cutoff_hz": metrics.cutoff_hz if metrics else None})
            shutil.rmtree(channel_dir, ignore_errors=True)
            return None, reason
        if verdict != "ok":
            store.log("download.spectrum_review", song_id=song_id,
                      detail={"channel": candidate.channel, "verdict": verdict,
                              "reason": reason,
                              "cutoff_hz": metrics.cutoff_hz if metrics else None})
            shutil.rmtree(channel_dir, ignore_errors=True)
            return None, f"需人工确认：{reason}"

    lyrics = ""
    if lyric_fetcher is not None:
        try:
            lyrics = strip_lyric_header(lyric_fetcher(song_id))
        except Exception:
            lyrics = ""

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
                      "verdict": verdict, "reason": reason,
                      "cutoff_hz": metrics.cutoff_hz if metrics else None,
                      "clean": report.after})
    return final_path, reason


def process_track(track: Any, channels: Sequence[Any], store: Store, *,
                  library: Path, staging: Path, lyric_fetcher=None,
                  pause_event=None, cancel_event=None, on_progress=None,
                  min_bitrate: float = 400.0, manual_bitrate: float = 600.0,
                  retries: int = 2, search_limiter: RateLimiter | None = None,
                  download_limiter: RateLimiter | None = None) -> TrackResult:
    started = time.monotonic()
    song_id = int(track["song_id"])
    quality = _target_quality(track)
    staging.mkdir(parents=True, exist_ok=True)
    library.mkdir(parents=True, exist_ok=True)

    all_candidates: list[Candidate] = []
    failures: list[str] = []
    for channel in channels:
        if _cancelled(cancel_event):
            break
        if not channel.available():
            continue
        try:
            if search_limiter is not None:
                search_limiter.wait(cancel_event)
            candidates = list(channel.resolve(track, quality))
        except Exception as exc:
            if _cancelled(cancel_event):
                break
            store.log("download.resolve_error", song_id=song_id,
                      detail={"channel": channel.name, "error": str(exc)})
            failures.append(f"{channel.name}: {exc}")
            continue
        all_candidates.extend(candidates)
        chosen, _basis = pick_candidate(track, candidates)
        if chosen is not None:
            attempts = [chosen] + [
                c for c in candidates
                if c is not chosen and c.url
                and c.song_id == int(track["song_id"])
            ]
        else:
            # Several scripts can resolve the same authoritative song id.  Keep
            # them all so a dead URL can fall through to the next source.
            attempts = [c for c in candidates
                        if c.url and c.song_id == int(track["song_id"])]
        if not attempts:
            continue

        for attempt in attempts:
            path, message = download_chosen(
                track, attempt, store, library=library, staging=staging,
                lyric_fetcher=lyric_fetcher,
                expected_lossless=quality in ("lossless", "hires"),
                pause_event=pause_event, cancel_event=cancel_event,
                on_progress=on_progress,
                min_bitrate=min_bitrate, manual_bitrate=manual_bitrate,
                retries=retries, rate_limiter=download_limiter)
            if path is not None:
                elapsed = int((time.monotonic() - started) * 1000)
                return TrackResult(song_id, "downloaded", attempt.channel,
                                   attempt.quality, str(path), message,
                                   elapsed, all_candidates)
            failures.append(message)
            if _cancelled(cancel_event):
                break
        if _cancelled(cancel_event):
            break

    elapsed = int((time.monotonic() - started) * 1000)
    if _cancelled(cancel_event):
        shutil.rmtree(staging / str(song_id), ignore_errors=True)
        store.log("download.cancelled", song_id=song_id, elapsed_ms=elapsed)
        return TrackResult(song_id, "cancelled", None, quality, None,
                           "已取消", elapsed, all_candidates)

    if not all_candidates:
        store.set_local_state(song_id, states.MATCH_FAILED)
        detail = "; ".join(dict.fromkeys(failures)) if failures else "所有来源都没有候选"
        store.log("download.match_failed", song_id=song_id,
                  detail={"reason": detail}, elapsed_ms=elapsed)
        return TrackResult(song_id, "failed", None, quality, None,
                           f"匹配失败：{detail}", elapsed, [])

    message = "；".join(dict.fromkeys(failures)) or "候选需要人工确认"
    store.set_local_state(song_id, states.PENDING_REVIEW)
    store.add_approval(song_id, message, [c.as_record() for c in all_candidates])
    store.log("download.needs_review", song_id=song_id,
              detail={"candidates": [c.as_record() for c in all_candidates],
                      "failures": failures}, elapsed_ms=elapsed)
    return TrackResult(song_id, "review", None, quality, None,
                       message, elapsed, all_candidates)


def _cancelled(event) -> bool:
    return event is not None and event.is_set()


def _wait_while_paused(pause_event, cancel_event) -> None:
    if pause_event is None:
        return
    while not pause_event.is_set():
        if _cancelled(cancel_event):
            raise DownloadCancelled("已取消")
        time.sleep(0.15)
