"""Thread-safe sliding-window limiter for search and download requests."""
from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """Reserve request slots so concurrent workers cannot burst past the window."""

    def __init__(self, min_interval: float = 0.0, per_minute: int = 0):
        self._min_interval = max(0.0, float(min_interval))
        self._per_minute = max(0, int(per_minute))
        self._lock = threading.Lock()
        self._last = 0.0
        self._events: deque[float] = deque()

    def wait(self, cancel_event=None) -> None:
        if self._min_interval <= 0 and self._per_minute <= 0:
            return
        with self._lock:
            now = time.monotonic()
            while self._events and self._events[0] <= now - 60.0:
                self._events.popleft()
            target = now
            if self._min_interval:
                target = max(target, self._last + self._min_interval)
            if self._per_minute and len(self._events) >= self._per_minute:
                target = max(target, self._events[0] + 60.0)
            self._last = target
            self._events.append(target)
        while True:
            remaining = target - time.monotonic()
            if remaining <= 0:
                return
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("已取消")
            time.sleep(min(0.1, remaining))
