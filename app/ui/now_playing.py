"""Full-page now-playing view, modelled on LX Music's play detail.

Left: album art (fetched from the cloud cover URL) with title and credits.
Right: lyrics as a list; the current line is highlighted and kept centred.
It is a page, not a dialog — the list page and this page swap places.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..core import covers
from . import theme
from .spectrum_bar import LiveSpectrum
from .spectrum_view import SegmentedControl, SpectrumView


def read_lyrics(path: Path) -> str:
    if path.suffix.lower() == ".flac":
        from mutagen.flac import FLAC

        tags = FLAC(path)
        lines = tags.get("LYRICS") or tags.get("lyrics") or []
    elif path.suffix.lower() == ".mp3":
        from mutagen.id3 import ID3

        lines = [frame.text for frame in ID3(path).getall("USLT")]
    else:
        return ""
    return lines[0] if lines else ""


def parse_stamp(line: str) -> int | None:
    """`[mm:ss.xx]` -> milliseconds."""
    line = line.strip()
    if not line.startswith("[") or "]" not in line:
        return None
    body = line[1:line.index("]")]
    try:
        minutes, rest = body.split(":")
        seconds = float(rest)
    except ValueError:
        return None
    return int((int(minutes) * 60 + seconds) * 1000)


def strip_stamp(line: str) -> str:
    if line.startswith("[") and "]" in line:
        return line[line.index("]") + 1:].strip()
    return line.strip()


class _CoverLoader(threading.Thread):
    """Reads from the on-disk cache first; only misses hit the network."""

    def __init__(self, url: str, callback):
        super().__init__(daemon=True)
        self._url, self._callback = url, callback

    def run(self) -> None:
        data = covers.load(self._url) or covers.fetch(self._url)
        self._callback(data or b"")


class NowPlayingPage(QWidget):
    back_requested = Signal()
    cover_ready = Signal(str, bytes)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._player = None
        self._stamps: list[int | None] = []
        self._current = -1
        self._cover_url = ""
        self._path: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 20, 36, 20)
        root.setSpacing(12)

        top = QHBoxLayout()
        back = QPushButton("‹ 返回列表")
        back.setObjectName("NavItem")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)
        top.addStretch(1)
        root.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(36)

        left = QVBoxLayout()
        left.setSpacing(12)
        self.cover = QLabel()
        self.cover.setFixedSize(320, 320)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setObjectName("Cover")
        left.addWidget(self.cover)
        self.title = QLabel("未在播放")
        self.title.setObjectName("NowTitle")
        self.title.setWordWrap(True)
        left.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setObjectName("PlaylistMeta")
        self.meta.setWordWrap(True)
        left.addWidget(self.meta)
        self.mode = SegmentedControl()
        self.mode.changed.connect(self._set_mode)
        left.addWidget(self.mode, 0, Qt.AlignLeft)
        left.addStretch(1)
        body.addLayout(left)

        self.lyrics = QListWidget()
        self.lyrics.setObjectName("LyricList")
        self.lyrics.setFocusPolicy(Qt.NoFocus)
        self.lyrics.setSelectionMode(QListWidget.NoSelection)
        self.lyrics.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.spectrum = SpectrumView()
        self.live = LiveSpectrum()
        self.spectrum_page = QWidget()
        spectrum_layout = QVBoxLayout(self.spectrum_page)
        spectrum_layout.setContentsMargins(0, 0, 0, 0)
        spectrum_layout.setSpacing(6)
        spectrum_layout.addWidget(self.spectrum, 1)
        spectrum_layout.addWidget(self.live)
        self.content = QStackedWidget()
        self.content.addWidget(self.lyrics)
        self.content.addWidget(self.spectrum_page)
        body.addWidget(self.content, 1)
        root.addLayout(body, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.cover_ready.connect(self._apply_cover)
        self._placeholder()

    # -- public -----------------------------------------------------------

    def show_track(self, path: Path, title: str, artist: str, album: str,
                   player, cover_url: str | None = None) -> None:
        self._path = path
        self.mode.set_index(0)
        self.content.setCurrentIndex(0)
        self.spectrum.clear()
        self.live.set_track(path, player)
        self.live.set_active(False)
        self.title.setText(title or path.stem)
        self.meta.setText("\n".join(part for part in (artist, album) if part))
        self._player = player
        self._current = -1
        self.lyrics.clear()
        self._stamps = []

        text = read_lyrics(path)
        if text:
            for line in text.splitlines():
                stamp = parse_stamp(line)
                content = strip_stamp(line)
                if not content:
                    self._stamps.append(stamp)
                    continue
                self._stamps.append(stamp)
                item = QListWidgetItem(content)
                item.setTextAlignment(Qt.AlignHCenter)
                self.lyrics.addItem(item)
        else:
            self.lyrics.addItem(QListWidgetItem("这首歌没有内嵌歌词。"))

        pixmap = self.cover.pixmap()
        has_cover = pixmap is not None and not pixmap.isNull()
        keep_cover = bool(cover_url and cover_url == self._cover_url and has_cover)
        if not keep_cover:
            self._placeholder()
        if cover_url and not keep_cover:
            self._cover_url = cover_url
            _CoverLoader(
                cover_url,
                lambda data, url=cover_url: self.cover_ready.emit(url, data),
            ).start()
        elif not cover_url:
            self._cover_url = ""
        self.timer.start(250)

    def stop(self) -> None:
        self.timer.stop()
        self.live.stop()
        self.spectrum.shutdown()
        self.mode.set_index(0)
        self.content.setCurrentIndex(0)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.resume_live()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.live.set_active(False)
        super().hideEvent(event)

    def resume_live(self) -> None:
        self.live.set_active(
            self.mode.current() == 1 and self.isVisible() and self._path is not None)

    def _set_mode(self, index: int) -> None:
        self.content.setCurrentIndex(1 if index else 0)
        self.live.set_active(
            bool(index) and self.isVisible() and self._path is not None)
        if index and self._path is not None:
            self.spectrum.show_path(self._path)
        else:
            self.spectrum.clear()

    # -- cover ------------------------------------------------------------

    def _placeholder(self) -> None:
        self.cover.setText("")
        self.cover.setStyleSheet(
            f"QLabel#Cover {{ background:{theme.PANEL_ALT}; border-radius:16px;"
            f" color:{theme.TEXT_FAINT}; }}")
        self.cover.setText("暂无封面")

    def _apply_cover(self, url: str, data: bytes) -> None:
        if url != self._cover_url:
            return
        if not data:
            self._placeholder()
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._placeholder()
            return
        scaled = pixmap.scaled(320, 320, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.cover.setPixmap(scaled)
        self.cover.setStyleSheet("QLabel#Cover { border-radius:16px; }")

    # -- lyrics follow ----------------------------------------------------

    def _tick(self) -> None:
        if self._player is None or not self._stamps:
            return
        position = self._player.position()
        target = -1
        for index, stamp in enumerate(self._stamps):
            if stamp is None:
                continue
            if stamp <= position:
                target = index
            else:
                break
        if target == self._current:
            return
        self._current = target
        self._highlight(target)

    def _highlight(self, target: int) -> None:
        normal = QFont(self.font())
        normal.setPointSizeF(10.5)
        active = QFont(self.font())
        active.setPointSizeF(12.0)
        active.setBold(True)
        for index in range(self.lyrics.count()):
            item = self.lyrics.item(index)
            item.setFont(active if index == target else normal)
            item.setForeground(QColor(theme.ACCENT if index == target else theme.TEXT_DIM))
        if 0 <= target < self.lyrics.count():
            self.lyrics.scrollToItem(self.lyrics.item(target), QListWidget.PositionAtCenter)
