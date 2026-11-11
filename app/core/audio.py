"""Audio probing and the fake-lossless spectrum check.

See docs/方案.md 8.4: the discriminator is the cliff between the 20-22 kHz band and
the 18-20 kHz band, not the absolute cutoff frequency.
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


def spectrum_delta(path: Path, seconds: float = 40.0) -> float | None:
    """Return mean(20-22k) - mean(18-20k) in dB, or None when undecidable.

    Genuine lossless measures roughly -20..0 dB; a 320k transcode lands below -55 dB.
    """
    try:
        import numpy as np
        import soundfile as sf
    except ImportError:  # pragma: no cover
        return None

    with sf.SoundFile(str(path)) as handle:
        sr = handle.samplerate
        total = len(handle)
        if total <= 0 or sr <= 44000:
            return None
        start = int(total * 0.33)
        n = min(int(sr * seconds), total - start)
        if n <= 0:
            return None
        data = handle.read(n, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    win, hop = 8192, 4096
    if len(mono) < win:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(mono, win)[::hop][:800]
    window = np.hanning(win).astype(np.float32)
    power = (np.abs(np.fft.rfft(frames * window, axis=1)) ** 2).mean(axis=0)
    db = 10 * np.log10(power + 1e-20)
    freqs = np.fft.rfftfreq(win, 1 / sr)

    def band(lo: float, hi: float) -> float | None:
        mask = (freqs >= lo) & (freqs < hi)
        return float(db[mask].mean()) if mask.any() else None

    hi_band = band(20000, 22000)
    mid_band = band(18000, 20000)
    if hi_band is None or mid_band is None:
        return None
    return round(hi_band - mid_band, 1)


def classify_lossless(info: AudioInfo, delta: float | None, *,
                      pass_db: float = -30.0, manual_db: float = -40.0) -> tuple[str, str]:
    """Return (verdict, reason). verdict is one of ok / suspicious / fake / unknown."""
    if not info.is_lossless_container:
        return "fake", f"容器不是无损格式（{info.fmt}）"
    if info.bitrate_kbps is not None and info.bitrate_kbps < 400:
        return "fake", f"平均码率仅 {info.bitrate_kbps:.0f} kbps，不可能是无损"
    if delta is None:
        return "unknown", "采样率过低或解码失败，无法做频谱判定"
    if delta > pass_db:
        return "ok", f"高频自然衰减（{delta} dB）"
    if delta > manual_db:
        return "suspicious", f"高频落差 {delta} dB，处于灰区"
    return "fake", f"高频断崖 {delta} dB，判定为转码"
