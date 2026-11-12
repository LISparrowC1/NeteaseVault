"""Thin live spectrum strip above the playback controls.

The strip reads a window around the current player position on every tick; it does
not cache decoded audio or rendered levels.  The background is intentionally
transparent so the player bar's own surface shows through.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ..core.spectrum import live_levels


class SpectrumBar(QWidget):
    BANDS = 64

    def __init__(self, player, parent: QWidget | None = None):
        super().__init__(parent)
        self._player = player
        self._path: Path | None = None
        self._active = False
        self._levels = [0.0] * self.BANDS
        self.setFixedHeight(26)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_path(self, path: Path | None) -> None:
        self._path = path
        self._levels = [0.0] * self.BANDS
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def _tick(self) -> None:
        if not self._active or self._path is None or not self.isVisible():
            return
        levels = live_levels(self._path, self._player.position(), bands=self.BANDS)
        if levels is not None:
            self._levels = [float(v) for v in levels]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = self.width()
        height = self.height()
        if width <= 0 or self._path is None:
            painter.end()
            return
        gap = 3.0
        slot = width / self.BANDS
        bar_width = 2.0
        for index, level in enumerate(self._levels):
            x = index * slot
            bar_height = max(1.5, (height - 5) * max(0.02, level))
            top = height - 2 - bar_height
            # Blue at the low end, purple at the peaks; 25% alpha columns.
            color = QColor(
                int(40 + 170 * level),
                int(70 + 20 * level),
                int(180 + 70 * level),
                64,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, top, bar_width, bar_height),
                                    bar_width / 2, bar_width / 2)
        painter.end()
