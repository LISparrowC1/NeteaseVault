"""Audio container probing.

Spectral analysis lives in :mod:`app.core.spectrum`; this module only reads the
container facts that must not be trusted from the file extension.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LOSSLESS_EXTS = {"flac", "wav", "ape", "alac", "aiff", "dsf"}

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"fLaC", "flac"),
    (b"ID3", "mp3"),
    (b"RIFF", "wav"),
    (b"OggS", "ogg"),
    (b"MAC ", "ape"),
    (b"\xff\xfb", "mp3"),
    (b"\xff\xf3", "mp3"),
    (b"\xff\xf2", "mp3"),
    (b"ftyp", "m4a"),
)


class AudioProbeError(RuntimeError):
    pass


def detect_format(path: Path) -> str | None:
    """Sniff the container from the first bytes. Declared extensions lie."""
    with path.open("rb") as handle:
        head = handle.read(16)
    for magic, fmt in _MAGIC:
        if head.startswith(magic):
            return fmt
    if head[4:8] == b"ftyp":
        return "m4a"
    return None


@dataclass
class AudioInfo:
    fmt: str
    samplerate: int
    channels: int
    bits: int | None
    duration_ms: int
    bitrate_kbps: float | None
    size_bytes: int | None = None

    @property
    def is_lossless_container(self) -> bool:
        return self.fmt.lower() in LOSSLESS_EXTS


def probe(path: Path) -> AudioInfo:
    """Read format facts without decoding the stream.

    Raises AudioProbeError when the container cannot be identified, so callers do not
    mistake an error page for audio.
    """
    size = path.stat().st_size
    if size < 1024:
        raise AudioProbeError(f"文件过小（{size} 字节），不是音频")
    ext = detect_format(path)
    if ext is None:
        raise AudioProbeError("无法识别的音频容器")
    if ext == "flac":
        from mutagen.flac import FLAC

        info = FLAC(path).info
        duration_ms = int(info.length * 1000)
        bitrate = size * 8 / info.length / 1000 if info.length else None
        return AudioInfo("flac", info.sample_rate, info.channels, info.bits_per_sample,
                         duration_ms, round(bitrate, 1) if bitrate else None, size)
    if ext == "mp3":
        from mutagen.mp3 import MP3

        info = MP3(path).info
        return AudioInfo("mp3", info.sample_rate, info.channels, None,
                         int(info.length * 1000), float(info.bitrate / 1000), size)
    # Anything else: let soundfile try.
    import soundfile as sf

    info = sf.info(str(path))
    duration_ms = int(info.frames / info.samplerate * 1000) if info.samplerate else 0
    bitrate = size * 8 / (duration_ms / 1000) / 1000 if duration_ms else None
    return AudioInfo(ext, info.samplerate, info.channels, None, duration_ms,
                     round(bitrate, 1) if bitrate else None, size)
