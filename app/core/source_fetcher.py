"""Fetch, validate and test public LX source scripts.

The fetcher deliberately keeps only a small, current set per repository: source
repositories often contain hundreds of historical copies.  Every downloaded script
is syntax-checked for the LX source contract and then asked to resolve a real
cloud song before it is installed.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from ..config import engine_dir, temp_dir
from .channels.source_channel import music_info
from .engine_client import EngineClient
from .netease import NeteaseClient
from ..db.store import Store

USER_AGENT = "NeteaseVault/1.2"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"


@dataclass
class Repo:
    owner: str
    name: str
    branch: str
    include: Callable[[str], bool]
    limit: int = 3


REPOS = [
    Repo("pdone", "lx-music-source", "main",
         lambda p: p.endswith("/latest.js"), 3),
    Repo("guoyue2010", "lxmusic-", "main",
         lambda p: p.startswith("V2603_latest/") and p.endswith(".js"), 3),
    Repo("shellsec", "lx-music-source", "master",
         lambda p: p.startswith("sources/") and p.endswith(".js"), 3),
    Repo("moxi5445", "lx-music-cloud", "main",
         lambda p: p.endswith(".js"), 1),
    Repo("Lingeng27", "lx-music-1010-source", "main",
         lambda p: p.endswith(".js"), 1),
    Repo("LuoXiaohei-2025", "LX-music-collection", "main",
         lambda p: p.startswith("Source of music/") and p.endswith(".js"), 1),
]

FALLBACK_URLS = [
    ("pdone", "changqing/latest.js"),
    ("pdone", "feichangdao/latest.js"),
    ("pdone", "fish/latest.js"),
    ("shellsec", "sources/xinghai/星海音乐源.js"),
    ("LuoXiaohei-2025", "Source of music/星海音乐源.js"),
]


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


def is_source(text: str) -> bool:
    if "@name" not in text or "sources" not in text:
        return False
    return "lx.send" in text or "send(" in text or "EVENT_NAMES.inited" in text


def _get_bytes(url: str) -> bytes | None:
    """Use requests when its CA store works; fall back to Windows curl.

    Some Windows networks use an interception CA that requests/certifi does not
    trust.  The system curl uses the Windows store and can still fetch GitHub.
    """
    try:
        response = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENT})
        if response.status_code == 200:
            return response.content
    except Exception:
        pass
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return None
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            [curl, "-fsSL", "--ssl-no-revoke", "--max-time", "25",
             "-A", USER_AGENT, url],
            capture_output=True, timeout=30, creationflags=flags)
        return result.stdout if result.returncode == 0 and result.stdout else None
    except Exception:
        return None


def _get_json(url: str) -> dict | None:
    data = _get_bytes(url)
    if not data:
        return None
    try:
        return __import__("json").loads(data.decode("utf-8"))
    except Exception:
        return None


def _tree(repo: Repo) -> list[str]:
    url = f"{API}/repos/{repo.owner}/{repo.name}/git/trees/{repo.branch}?recursive=1"
    data = _get_json(url)
    if not data:
        return []
    return [item["path"] for item in data.get("tree", [])
            if item.get("type") == "blob"]


def _download(owner: str, name: str, branch: str, path: str) -> tuple[bytes, str] | None:
    url = f"{RAW}/{owner}/{name}/{branch}/{urllib.parse.quote(path, safe='/')}"
    data = _get_bytes(url)
    if not data:
        return None
    return data, url


def _candidate_name(owner: str, path: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", Path(path).stem)[:48]
    return f"auto-{owner}-{stem}.js"


def fetch_candidates(progress: Callable[[str], None] | None = None) -> list[tuple[str, str, str]]:
    """Return (owner, path, text) candidates from all configured repositories."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for repo in REPOS:
        if progress:
            progress(f"发现 {repo.owner}/{repo.name}…")
        paths = [p for p in _tree(repo) if repo.include(p)][:repo.limit]
        for path in paths:
            got = _download(repo.owner, repo.name, repo.branch, path)
            if got is None:
                continue
            data, _url = got
            text = _decode(data)
            if not is_source(text):
                continue
            digest = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            out.append((repo.owner, path, text))
    if not out:
        for owner, path in FALLBACK_URLS:
            repo = next((r for r in REPOS if r.owner == owner), None)
            if repo is None:
                continue
            got = _download(repo.owner, repo.name, repo.branch, path)
            if got is None:
                continue
            text = _decode(got[0])
            if is_source(text):
                out.append((owner, path, text))
    return out


def cloud_sample(cookie: str, db_path: Path) -> dict:
    """Pick the first not-yet-downloaded song from the cloud liked list."""
    client = NeteaseClient(cookie, min_interval=1.2)
    profile = client.account()
    playlist_id = client.liked_playlist_id(int(profile["userId"]))
    entries = client.playlist_track_ids(playlist_id)
    if not entries:
        raise RuntimeError("「我喜欢的音乐」为空")

    probe = Store(db_path)
    try:
        existing = probe.existing_track_ids()
    finally:
        probe.close()
    chosen = next(
        (entry for entry in entries
         if not (existing.get(int(entry["id"]))
                 and existing[int(entry["id"])]["local_rel_path"])),
        entries[0])
    details = client.songs_detail([chosen["id"]])
    if not details:
        raise RuntimeError("云端没有返回样本详情")
    song = details[0]
    return music_info({
        "song_id": int(song["id"]),
        "title": song.get("name"),
        "artist": "、".join(a.get("name", "") for a in (song.get("ar") or [])),
        "album": (song.get("al") or {}).get("name"),
        "duration_ms": song.get("dt"),
    })


def install_candidates(candidates: list[tuple[str, str, str]], cookie: str,
                       db_path: Path, scripts_dir: Path,
                       progress: Callable[[str], None] | None = None) -> list[str]:
    """Test candidates with the engine; copy only ones that resolve a real song."""
    if not candidates:
        return []
    info = cloud_sample(cookie, db_path)
    work = Path(tempfile.mkdtemp(prefix="lx-fetch-", dir=temp_dir()))
    engine = EngineClient(engine_dir(), user_scripts_dir=work)
    installed: list[str] = []
    try:
        mapping: dict[str, tuple[str, str, str]] = {}
        for index, (owner, path, text) in enumerate(candidates):
            filename = f"candidate-{index:03d}.js"
            (work / filename).write_text(text, encoding="utf-8")
            mapping[filename] = (owner, path, text)
        if progress:
            progress(f"正在加载 {len(mapping)} 个候选源…")
        scripts = engine.call("scripts", timeout=180)
        for item in scripts:
            filename = item.get("file")
            if filename not in mapping or item.get("error") or not item.get("ready"):
                continue
            sources = item.get("sources") or {}
            if "wy" not in sources:
                continue
            qualities = sources["wy"].get("qualitys") or []
            quality = "flac" if "flac" in qualities else (qualities[0] if qualities else "")
            if progress:
                progress(f"测试 {mapping[filename][0]}/{Path(mapping[filename][1]).name}…")
            try:
                engine.call("resolve", {
                    "file": filename, "source": "wy", "quality": quality,
                    "musicInfo": info,
                }, timeout=20)
            except Exception:
                continue
            installed.append(filename)
    finally:
        engine.shutdown()
        shutil.rmtree(work, ignore_errors=True)

    scripts_dir.mkdir(parents=True, exist_ok=True)
    if not installed:
        return []
    for old in scripts_dir.glob("auto-*.js"):
        old.unlink(missing_ok=True)
    written = []
    for filename in installed:
        owner, path, text = mapping[filename]
        target = scripts_dir / _candidate_name(owner, path)
        counter = 1
        while target.exists():
            target = scripts_dir / f"{target.stem}-{counter}.js"
            counter += 1
        target.write_text(text, encoding="utf-8")
        written.append(target.name)
    return written
