"""Soft, folder-local notification sound.

Windows' default message-box beep is loud and jarring.  This generates two quiet
sine pips inside ``data/tmp`` and plays them asynchronously instead.
"""
from __future__ import annotations

import math
import os
import struct
import threading
import time
import wave

from ..config import data_dir

_lock = threading.Lock()
_last_played = 0.0


def _wav_path():
    root = data_dir() / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root / "notify.wav"


def _write_wav(path) -> None:
    rate = 22050
    frames = bytearray()
    for frequency, duration in ((880.0, 0.085), (660.0, 0.085)):
        count = int(rate * duration)
        for index in range(count):
            envelope = min(1.0, index / (rate * 0.012),
                            (count - index) / (rate * 0.012))
            sample = int(32767 * 0.12 * envelope *
                         math.sin(2.0 * math.pi * frequency * index / rate))
            frames.extend(struct.pack("<h", sample))
        gap = int(rate * 0.075)
        frames.extend(b"\x00\x00" * gap)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


def soft_beep() -> None:
    global _last_played
    if os.name != "nt":
        return
    try:
        import winsound
    except ImportError:
        return
    now = time.monotonic()
    with _lock:
        if now - _last_played < 0.25:
            return
        _last_played = now
        path = _wav_path()
        try:
            if not path.exists() or path.stat().st_size < 1000:
                _write_wav(path)
            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC |
                winsound.SND_NODEFAULT | winsound.SND_NOSTOP)
        except OSError:
            return
