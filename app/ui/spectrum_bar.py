"""Live spectrum for the spectrum page.

The visualiser reads a short PCM window and mirrors each band above and below a
horizontal centre line.  Bars are contiguous, so the result reads as a compact
top/bottom mirrored analyser.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ..core.spectrum import live_levels


class LiveSpectrum(QWidget):
    BANDS = 64

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._player = None
        self._path: Path | None = None
        self._active = False
        self._levels = [0.0] * self.BANDS
        self.setFixedSize(300, 55)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self._timer = QTimer(self)
        self._timer.setInterval(75)
        self._timer.timeout.connect(self._tick)

    def set_track(self, path: Path, player) -> None:
        self._path = path
        self._player = player
        self._levels = [0.0] * self.BANDS
        self.set_active(True)
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def stop(self) -> None:
        self.set_active(False)
        self._path = None
        self._player = None
        self._levels = [0.0] * self.BANDS
        self.update()

    def _tick(self) -> None:
        if not self._active or self._path is None or self._player is None:
            return
        if not self.isVisible():
            return
        levels = live_levels(self._path, self._player.position(), bands=self.BANDS)
        if levels is not None:
            self._levels = [float(v) for v in levels]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        if self._path is None:
            painter.end()
            return
        width = self.width()
        height = self.height()
        center = height / 2.0
        slot = width / self.BANDS
        bar_width = slot + 0.6
        for index, level in enumerate(self._levels):
            bar_height = max(1.0, (center - 3) * max(0.02, level))
            x = index * slot
            color = QColor(
                int(10 + 80 * level),
                int(20 + 30 * level),
                int(80 + 60 * level),
                128,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRect(QRectF(x, center - bar_height, bar_width, bar_height))
            painter.drawRect(QRectF(x, center, bar_width, bar_height))
        painter.end()
