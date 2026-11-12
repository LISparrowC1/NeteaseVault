"""Spectral analysis and spectrogram rendering.

The download gate only needs a few aggregate numbers; the playback page needs the
full time-frequency matrix.  Both use the same decoded PCM so the visual and the
verdict cannot disagree.  Nothing here touches the disk cache: the matrix is built
on demand and released with the widget.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np


class SpectrumError(RuntimeError):
    """The file could not be decoded or was too short for a spectrum."""


@dataclass(frozen=True)
class SpectralMetrics:
    sample_rate: int
    duration_ms: int
    cutoff_hz: float
    high_band_delta_db: float | None
    cliff_db: float | None
    peak_db: float
    noise_db: float


@dataclass
class Spectrogram:
    levels: np.ndarray          # float32, shape (height, width), 0..1
    duration_s: float
    sample_rate: int
    max_freq_hz: float


def _decode_mono(path: Path, *, start_frame: int = 0, frames: int = -1) -> tuple[np.ndarray, int]:
    import soundfile as sf

    with sf.SoundFile(str(path)) as handle:
        if start_frame:
            handle.seek(min(start_frame, len(handle)))
        data = handle.read(frames=frames, dtype="float32", always_2d=True)
        rate = int(handle.samplerate)
    if data.size == 0:
        return np.zeros(0, dtype=np.float32), rate
    return data.mean(axis=1).astype(np.float32), rate


def _average_spectrum(mono: np.ndarray, sample_rate: int, fft_size: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    """Return (frequencies, average power in dB) over a bounded slice."""
    if mono.size < fft_size:
        raise SpectrumError("音频太短，无法分析频谱")
    hop = fft_size // 2
    frames = np.lib.stride_tricks.sliding_window_view(mono, fft_size)[::hop]
    if len(frames) > 400:
        frames = frames[:400]
    window = np.hanning(fft_size).astype(np.float32)
    power = (np.abs(np.fft.rfft(frames * window, axis=1)) ** 2).mean(axis=0)
    db = 10.0 * np.log10(power + 1e-20)
    freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
    return freqs, db


def _band_mean(freqs: np.ndarray, db: np.ndarray, lo: float, hi: float) -> float | None:
    mask = (freqs >= lo) & (freqs < hi)
    if not mask.any():
        return None
    return float(db[mask].mean())


def analyze_file(path: Path, seconds: float = 60.0) -> SpectralMetrics:
    """Measure cutoff, high-band drop and cliff from a sample near the middle.

    The sample intentionally ignores the first/last thirds: intros and fades are not
    representative of the codec's bandwidth.  No image is produced here.
    """
    import soundfile as sf

    with sf.SoundFile(str(path)) as handle:
        rate = int(handle.samplerate)
        total = len(handle)
    if rate <= 0 or total <= 0:
        raise SpectrumError("无法读取音频参数")
    start = int(total * 0.33)
    want = max(4096, min(int(rate * seconds), total - start))
    mono, rate = _decode_mono(path, start_frame=start, frames=want)
    if mono.size < 4096:
        mono, rate = _decode_mono(path, frames=want)
    freqs, db = _average_spectrum(mono, rate)

    nyquist = rate / 2.0
    upper = min(nyquist, 24000.0)
    bands: list[tuple[float, float]] = []
    edge = 500.0
    while edge <= upper:
        lo, hi = edge - 500.0, edge
        value = _band_mean(freqs, db, lo, hi)
        if value is not None:
            bands.append((edge - 250.0, value))
        edge += 500.0
    if not bands:
        raise SpectrumError("频谱为空")
    peak_db = max(v for _, v in bands)
    sorted_db = sorted(v for _, v in bands)
    noise_db = float(np.median(sorted_db[: max(1, len(sorted_db) // 5)]))
    threshold = max(peak_db - 80.0, -110.0)
    cutoff = 0.0
    for freq, value in bands:
        if value >= threshold:
            cutoff = freq + 250.0
    if cutoff <= 0:
        cutoff = bands[0][0] + 250.0

    high = _band_mean(freqs, db, 20000, 22000)
    mid = _band_mean(freqs, db, 18000, 20000)
    delta = round(high - mid, 1) if high is not None and mid is not None else None

    # Largest drop between adjacent 1 kHz bands in the top octave.  A codec cliff is
    # a sharp step; a natural acoustic roll-off is gradual.
    cliff: float | None = None
    top = [(f, v) for f, v in bands if 14000 <= f <= min(22000, nyquist)]
    for (_, a), (_, b) in zip(top, top[1:]):
        drop = a - b
        if drop > 0 and (cliff is None or drop > cliff):
            cliff = float(drop)

    return SpectralMetrics(
        sample_rate=rate,
        duration_ms=int(total / rate * 1000),
        cutoff_hz=round(cutoff, 1),
        high_band_delta_db=delta,
        cliff_db=round(cliff, 1) if cliff is not None else None,
        peak_db=round(peak_db, 1),
        noise_db=round(noise_db, 1),
    )


def classify_metrics(metrics: SpectralMetrics, *, bitrate_kbps: float | None,
                     min_bitrate: float = 400.0,
                     manual_bitrate: float = 600.0,
                     cutoff_fake: float = 18000.0,
                     cutoff_manual: float = 20000.0) -> tuple[str, str]:
    """Return (verdict, reason), verdict in ok / suspicious / fake / unknown."""
    if bitrate_kbps is not None and bitrate_kbps < min_bitrate:
        return "fake", f"平均码率仅 {bitrate_kbps:.0f} kbps，不可能是无损"
    if bitrate_kbps is not None and bitrate_kbps < manual_bitrate:
        return "suspicious", f"平均码率 {bitrate_kbps:.0f} kbps，处于灰区"
    if metrics is None:
        return "unknown", "无法分析频谱"
    if metrics.cutoff_hz < cutoff_fake:
        return "fake", f"频谱截止在 {metrics.cutoff_hz / 1000:.1f} kHz，判定为转码"
    if metrics.cutoff_hz < cutoff_manual:
        return "suspicious", f"频谱截止在 {metrics.cutoff_hz / 1000:.1f} kHz，处于灰区"
    if metrics.cliff_db is not None and metrics.cliff_db >= 40.0:
        return "suspicious", f"高频出现 {metrics.cliff_db:.0f} dB 断崖，需人工确认"
    return "ok", f"频谱截止在 {metrics.cutoff_hz / 1000:.1f} kHz"


def render_spectrogram(path: Path, *, width: int = 900, height: int = 320,
                       fft_size: int = 2048,
                       progress: Callable[[float], None] | None = None,
                       cancelled: Callable[[], bool] | None = None) -> Spectrogram:
    """Build a full-track, linear-frequency spectrogram matrix for display.

    The matrix is normalized to 0..1; the UI owns the palette and axes.  It is not
    written anywhere, so repeated views cost CPU but never disk.
    """
    import soundfile as sf

    with sf.SoundFile(str(path)) as handle:
        rate = int(handle.samplerate)
        total = len(handle)
    if rate <= 0 or total < fft_size * 2:
        raise SpectrumError("音频太短，无法绘制频谱图")
    mono, rate = _decode_mono(path)
    if mono.size < fft_size * 2:
        raise SpectrumError("音频太短，无法绘制频谱图")

    hop = max(fft_size // 2, int(np.ceil((mono.size - fft_size) / max(1, width * 2))))
    frames = np.lib.stride_tricks.sliding_window_view(mono, fft_size)[::hop]
    if len(frames) == 0:
        raise SpectrumError("没有足够的音频帧")
    window = np.hanning(fft_size).astype(np.float32)
    bins = np.fft.rfftfreq(fft_size, 1.0 / rate)
    freqs = np.linspace(0, rate / 2.0, height + 1)
    if cancelled is not None and cancelled():
        raise SpectrumError("已取消")
    power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
    db = 10.0 * np.log10(power + 1e-20)

    # Frequency bins are ordered, so reduce them directly into display rows.
    row_bounds = np.searchsorted(bins, freqs, side="left")
    row_bounds = np.maximum.accumulate(row_bounds)
    row_bounds = np.minimum(row_bounds, len(bins) - 1)
    row_sums = np.add.reduceat(db, row_bounds[:-1], axis=1)
    row_counts = np.maximum(1, np.diff(row_bounds))
    rows = (row_sums / row_counts).T  # (height, frames)

    # Resample time columns; clamp duplicate boundaries when the widget is wider
    # than the number of analysed frames.
    col_bounds = np.searchsorted(np.arange(len(frames)), np.linspace(0, len(frames), width + 1),
                                 side="left")
    col_bounds = np.maximum.accumulate(col_bounds)
    col_bounds = np.minimum(col_bounds, len(frames) - 1)
    col_sums = np.add.reduceat(rows, col_bounds[:-1], axis=1)
    col_counts = np.maximum(1, np.diff(col_bounds))
    columns = (col_sums / col_counts).astype(np.float32)
    columns = np.clip((columns + 120.0) / 120.0, 0.0, 1.0)
    if progress is not None:
        progress(1.0)
    return Spectrogram(columns, total / rate, rate, rate / 2.0)


def live_levels(path: Path, position_ms: int, *, bands: int = 48,
                fft_size: int = 4096) -> np.ndarray | None:
    """Current-position band levels (0..1) for the translucent playback strip."""
    import soundfile as sf

    try:
        with sf.SoundFile(str(path)) as handle:
            rate = int(handle.samplerate)
            if rate <= 0:
                return None
            start = max(0, int(position_ms * rate / 1000) - fft_size // 2)
            handle.seek(min(start, len(handle)))
            data = handle.read(frames=fft_size, dtype="float32", always_2d=True)
            if data.size == 0:
                return None
            mono = data.mean(axis=1)
            if mono.size < fft_size:
                mono = np.pad(mono, (0, fft_size - mono.size))
            spectrum = np.abs(np.fft.rfft(mono * np.hanning(fft_size))) ** 2
            db = 10.0 * np.log10(spectrum + 1e-20)
            freqs = np.fft.rfftfreq(fft_size, 1.0 / rate)
            out = np.zeros(bands, dtype=np.float32)
            edges = np.geomspace(40.0, min(16000.0, rate / 2.0), bands + 1)
            for i in range(bands):
                mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
                if mask.any():
                    out[i] = float(db[mask].mean())
            return np.clip((out + 80.0) / 80.0, 0.0, 1.0)
    except Exception:
        return None
