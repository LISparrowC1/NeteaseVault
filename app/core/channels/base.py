"""Channel contract shared by musicdl / LX source scripts / the official API."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass
class Candidate:
    """One concrete thing we could download for a track."""

    channel: str                      # musicdl / source / official
    source: str                       # wy / kw / tx / mg / kg
    url: str | None
    quality: str                      # requested tier that produced this
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int | None = None
    size_bytes: int | None = None
    ext: str | None = None
    song_id: int | None = None        # platform-native id, when known
    # "song_id" means the candidate was resolved from the same id as the track, which
    # is stronger than any metadata comparison. "metadata" means it came from a search.
    match_basis: str = "metadata"
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel, "source": self.source, "quality": self.quality,
            "title": self.title, "artist": self.artist, "album": self.album,
            "duration_ms": self.duration_ms, "size_bytes": self.size_bytes,
            "ext": self.ext, "song_id": self.song_id, "match_basis": self.match_basis,
            "has_url": bool(self.url),
        }

    def as_record(self) -> dict[str, Any]:
        """Persistable form: keeps the URL so manual approval can retry quickly."""
        record = self.as_dict()
        record["url"] = self.url
        record["raw"] = self.raw
        return record

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Candidate":
        return cls(
            channel=record.get("channel", ""),
            source=record.get("source", ""),
            url=record.get("url"),
            quality=record.get("quality", ""),
            title=record.get("title", ""),
            artist=record.get("artist", ""),
            album=record.get("album", ""),
            duration_ms=record.get("duration_ms"),
            size_bytes=record.get("size_bytes"),
            ext=record.get("ext"),
            song_id=record.get("song_id"),
            match_basis=record.get("match_basis", "metadata"),
            raw=record.get("raw") or {},
        )


class Channel(Protocol):
    name: str

    def available(self) -> bool:
        """False when the channel cannot run at all (missing runtime, disabled)."""

    def resolve(self, track: Any, quality: str) -> Sequence[Candidate]:
        """Return candidates for one track. Must not raise for ordinary failures."""
