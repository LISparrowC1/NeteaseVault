"""Minimal client for the netease web API.

Only the endpoints this project actually needs, each verified against a live
account while designing the tool:

* account        -- who owns the cookie
* liked playlist -- specialType == 5
* track ids      -- carries the per-track `at` (added time, milliseconds)
* song detail    -- track metadata plus `privileges` (quality / playability)
* lyric          -- LRC and translation, no login required
* song url       -- direct media URL by quality tier
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterable

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BASE = "https://music.163.com"

# Quality tiers the endpoints understand, ordered from best to worst.
QUALITY_BR = {
    "hires": 1900000,
    "lossless": 999000,
    "exhigh": 320000,
    "standard": 128000,
}


class NeteaseError(RuntimeError):
    pass


class NeteaseClient:
    def __init__(self, cookie: str, timeout: int = 20, min_interval: float = 0.0):
        if not cookie.strip():
            raise NeteaseError("cookie 为空")
        self._cookie = cookie
        self._timeout = timeout
        self._min_interval = min_interval
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": UA,
            "Referer": f"{BASE}/",
        })
        self._session.cookies.set("__dummy", "1", domain=".music.163.com")

    # -- plumbing ---------------------------------------------------------

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        self._throttle()
        headers = {"Cookie": self._cookie}
        url = f"{BASE}{path}"
        try:
            resp = self._session.request(method, url, headers=headers, timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            raise NeteaseError(f"请求失败: {exc}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise NeteaseError(f"非 JSON 响应 ({resp.status_code}): {resp.text[:200]}") from exc
        code = data.get("code")
        if code != 200:
            raise NeteaseError(f"{path} 返回 code={code}: {json.dumps(data, ensure_ascii=False)[:300]}")
        return data

    # -- account / playlist ----------------------------------------------

    def account(self) -> dict[str, Any]:
        data = self._request("GET", "/api/nuser/account/get")
        profile = data.get("profile") or {}
        if not profile.get("userId"):
            raise NeteaseError("cookie 无效或已过期（未拿到用户信息）")
        return profile

    def playlist_summary(self, playlist_id: int) -> dict[str, Any]:
        data = self._request("GET", "/api/v6/playlist/detail", params={"id": playlist_id, "n": 0})
        playlist = data.get("playlist") or {}
        if not playlist:
            raise NeteaseError(f"歌单 {playlist_id} 不存在或无权限")
        return playlist

    def liked_playlist_id(self, uid: int) -> int:
        data = self._request("GET", "/api/user/playlist", params={"uid": uid, "limit": 1000, "offset": 0})
        plays = data.get("playlist") or []
        for item in plays:
            if item.get("specialType") == 5:
                return int(item["id"])
        for item in plays:
            if item.get("name") in ("我喜欢的音乐", "喜欢的音乐"):
                return int(item["id"])
        raise NeteaseError("未找到“我喜欢的音乐”歌单")

    def playlist_track_ids(self, playlist_id: int) -> list[dict[str, Any]]:
        """Return [{id, at, ...}] in cloud order; `at` is the added time."""
        data = self._request("GET", "/api/v6/playlist/detail", params={"id": playlist_id, "n": 1000})
        playlist = data.get("playlist") or {}
        ids = playlist.get("trackIds") or []
        if not ids:
            raise NeteaseError("歌单为空或接口未返回 trackIds")
        return [{"id": int(x["id"]), "at": x.get("at")} for x in ids]

    def songs_detail(self, song_ids: Iterable[int], chunk: int = 400) -> list[dict[str, Any]]:
        """Fetch metadata plus privileges; results keep the requested order."""
        ids = list(song_ids)
        out: list[dict[str, Any]] = []
        for start in range(0, len(ids), chunk):
            part = ids[start:start + chunk]
            payload = json.dumps([{"id": i} for i in part], separators=(",", ":"))
            data = self._request("POST", "/api/v3/song/detail", data={"c": payload})
            songs = data.get("songs") or []
            privs = {int(p.get("id", -1)): p for p in (data.get("privileges") or [])}
            for song in songs:
                song["_privilege"] = privs.get(int(song.get("id", -1)), {})
            out.extend(songs)
        by_id = {int(s["id"]): s for s in out}
        return [by_id[i] for i in ids if i in by_id]

    # -- lyric / url ------------------------------------------------------

    def lyric(self, song_id: int) -> dict[str, str]:
        data = self._request("GET", "/api/song/lyric", params={"id": song_id, "lv": 1, "kv": 1, "tv": -1})
        return {
            "lyric": (data.get("lrc") or {}).get("lyric") or "",
            "tlyric": (data.get("tlyric") or {}).get("lyric") or "",
        }

    def lyric_text(self, song_id: int) -> str:
        """Plain LRC for embedding; empty string when the song has no lyric."""
        return self.lyric(song_id)["lyric"]

    def song_url(self, song_id: int, quality: str) -> dict[str, Any] | None:
        br = QUALITY_BR.get(quality)
        if br is None:
            raise ValueError(f"未知音质档位: {quality}")
        data = self._request(
            "GET", "/api/song/enhance/player/url",
            params={"ids": json.dumps([song_id], separators=(",", ":")), "br": br},
        )
        rows = data.get("data") or []
        return rows[0] if rows else None
