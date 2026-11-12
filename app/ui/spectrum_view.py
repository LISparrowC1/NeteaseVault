"""Playback-page spectrum widgets.

The static view builds its matrix on a worker thread and keeps it only in memory.
The segmented control is the small sliding pill that switches lyrics -> spectrum.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QThread, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core.spectrum import Spectrogram, SpectrumError, render_spectrogram
from . import theme


def _palette(levels: np.ndarray) -> np.ndarray:
    """Spek's default SoX palette, with the 0..-120 dB range."""
    level = np.clip(levels, 0.0, 1.0)
    red = np.where(level >= 0.73, 1.0,
                   np.where(level >= 0.13,
                            np.sin((level - 0.13) / 0.60 * np.pi / 2.0), 0.0))
    green = np.where(level >= 0.91, 1.0,
                     np.where(level >= 0.60,
                              np.sin((level - 0.60) / 0.31 * np.pi / 2.0), 0.0))
    blue = np.where(level < 0.60, 0.5 * np.sin(level / 0.60 * np.pi),
                    np.where(level >= 0.78, (level - 0.78) / 0.22, 0.0))
    out = np.empty(levels.shape + (4,), dtype=np.uint8)
    out[..., 0] = np.clip(red * 255.0 + 0.5, 0, 255)
    out[..., 1] = np.clip(green * 255.0 + 0.5, 0, 255)
    out[..., 2] = np.clip(blue * 255.0 + 0.5, 0, 255)
    out[..., 3] = 255
    return out


class _RenderWorker(QThread):
    done = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, token: int, path: Path, width: int, height: int):
        super().__init__()
        self._token, self._path = token, path
        self._width, self._height = width, height
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            spec = render_spectrogram(
                self._path, width=self._width, height=self._height,
                cancelled=self._cancel.is_set)
        except SpectrumError as exc:
            self.failed.emit(self._token, str(exc))
        except Exception as exc:
            self.failed.emit(self._token, f"频谱生成失败: {exc}")
        else:
            if not self._cancel.is_set():
                self.done.emit(self._token, spec)


class SpectrumView(QWidget):
    """Static full-track spectrogram with frequency/time rulers."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._path: Path | None = None
        self._spec: Spectrogram | None = None
        self._loading = False
        self._message = ""
        self._token = 0
        self._worker: _RenderWorker | None = None
        self._workers: set[_RenderWorker] = set()
        self.setMinimumHeight(260)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def show_path(self, path: Path) -> None:
        self.clear()
        self._path = path
        self._loading = True
        self._message = "正在生成整首频谱…"
        self._token += 1
        token = self._token
        width = max(500, self.width() - 72)
        height = max(220, self.height() - 44)
        worker = _RenderWorker(token, path, width, height)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(lambda w=worker: self._forget_worker(w))
        worker.finished.connect(worker.deleteLater)
        self._workers.add(worker)
        self._worker = worker
        worker.start()
        self.update()

    def clear(self) -> None:
        self._token += 1
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._spec = None
        self._loading = False
        self._message = ""
        self.update()

    def shutdown(self) -> None:
        """Stop all render threads before the page (or app) is destroyed."""
        self.clear()
        for worker in list(self._workers):
            worker.cancel()
            worker.wait(5000)
        self._workers.clear()

    def _forget_worker(self, worker: _RenderWorker) -> None:
        self._workers.discard(worker)
        if self._worker is worker:
            self._worker = None

    def _on_done(self, token: int, spec: Spectrogram) -> None:
        if token != self._token:
            return
        self._spec = spec
        self._loading = False
        self._message = ""
        self._worker = None
        self.update()

    def _on_failed(self, token: int, message: str) -> None:
        if token != self._token:
            return
        self._loading = False
        self._message = message
        self._worker = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = self.rect().adjusted(46, 10, -20, -24)
        if rect.width() < 20 or rect.height() < 20:
            painter.end()
            return
        if self._spec is None:
            painter.setPen(QColor(theme.TEXT_FAINT))
            font = QFont(self.font())
            font.setPointSizeF(10.0)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter,
                             self._message or "点击「频谱」查看整首频谱")
            painter.end()
            return

        levels = np.flipud(self._spec.levels)
        rgba = _palette(levels)
        height, width = levels.shape
        image = QImage(rgba.data, width, height, width * 4, QImage.Format_RGBA8888).copy()
        painter.drawImage(rect, image)

        # Frame and grid.
        painter.setPen(QPen(QColor(theme.DIVIDER), 1))
        painter.drawRect(rect)
        font = QFont(self.font())
        font.setPointSizeF(7.5)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_FAINT))
        for freq in (0, 5000, 10000, 15000, 20000):
            if freq > self._spec.max_freq_hz:
                continue
            y = rect.bottom() - rect.height() * freq / self._spec.max_freq_hz
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.drawText(QRectF(0, y - 7, 42, 14), Qt.AlignRight | Qt.AlignVCenter,
                             f"{freq // 1000}k" if freq else "0")
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = rect.left() + rect.width() * fraction
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            seconds = int(self._spec.duration_s * fraction)
            label = f"{seconds // 60}:{seconds % 60:02d}"
            painter.drawText(QRectF(x - 24, rect.bottom() + 4, 48, 16),
                             Qt.AlignCenter, label)

        # Color legend, top-right inside the plot.
        legend = QRectF(rect.right() - 12, rect.top() + 4, 7, rect.height() - 8)
        for i in range(int(legend.height())):
            level = 1.0 - i / max(1.0, legend.height())
            color = _palette(np.array([[level]], dtype=np.float32))[0, 0]
            painter.setPen(QColor(int(color[0]), int(color[1]), int(color[2]), int(color[3])))
            painter.drawLine(QPointF(legend.left(), legend.top() + i),
                             QPointF(legend.right(), legend.top() + i))
        painter.end()


class SegmentedControl(QWidget):
    """Two-segment sliding pill: 歌词 / 频谱."""

    changed = Signal(int)

    def __init__(self, labels: tuple[str, str] = ("歌词", "频谱"),
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._labels = labels
        self._index = 0
        self._offset = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.setFixedSize(168, 34)
        self.setCursor(Qt.PointingHandCursor)

    def current(self) -> int:
        return self._index

    def set_index(self, index: int, *, emit: bool = False) -> None:
        index = 1 if index else 0
        if index == self._index:
            return
        self._index = index
        self._animate()
        if emit:
            self.changed.emit(index)

    def _animate(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(float(self._index))
        self._anim.start()

    def _on_anim(self, value) -> None:
        self._offset = float(value)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.set_index(0 if event.position().x() < self.width() / 2 else 1, emit=True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        radius = self.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.PANEL_ALT))
        painter.drawRoundedRect(self.rect(), radius, radius)
        segment = self.width() / 2
        x = self._offset * segment + 3
        painter.setBrush(QColor(theme.ACCENT_DIM))
        painter.drawRoundedRect(QRectF(x, 3, segment - 6, self.height() - 6),
                                radius - 3, radius - 3)
        font = QFont(self.font())
        font.setPointSizeF(9.0)
        font.setBold(True)
        painter.setFont(font)
        for i, label in enumerate(self._labels):
            painter.setPen(QColor(theme.TEXT if i == self._index else theme.TEXT_DIM))
            painter.drawText(QRectF(i * segment, 0, segment, self.height()),
                             Qt.AlignCenter, label)
        painter.end()
