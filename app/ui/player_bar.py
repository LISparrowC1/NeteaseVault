"""Bottom playback bar.

One row: track info, transport controls, elapsed time, progress, volume (icon shows
the level on hover and mutes when clicked), then the queue button.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QSlider, QVBoxLayout, QWidget)

from . import theme
from .audio_route import FollowDefaultOutput, audio_error_dialog
from .icons import outline_icon


def _fmt(ms: int) -> str:
    seconds = max(0, int(ms)) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


class VolumeButton(QPushButton):
    """Speaker glyph; shows the percentage on hover; click toggles mute."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("VolumeButton")
        self._level = 70
        self._muted = False
        self._hover = False
        self.setMouseTracking(True)

    def set_level(self, level: int, muted: bool) -> None:
        self._level = level
        self._muted = muted
        self.setToolTip("已静音" if muted else f"音量 {level}%")
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = QColor(theme.TEXT if self._hover else theme.TEXT_DIM)
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self._hover:
            font = painter.font()
            font.setPointSizeF(8.0)
            font.setBold(True)
            painter.setFont(font)
            text = "静音" if self._muted else f"{self._level}"
            painter.drawText(self.rect(), Qt.AlignCenter, text)
            painter.end()
            return

        # speaker body
        body = QPainterPath()
        body.moveTo(6, 12)
        body.lineTo(11, 12)
        body.lineTo(17, 7)
        body.lineTo(17, 23)
        body.lineTo(11, 18)
        body.lineTo(6, 18)
        body.closeSubpath()
        painter.drawPath(body)

        if self._muted:
            painter.drawLine(QPointF(21, 12), QPointF(27, 18))
            painter.drawLine(QPointF(27, 12), QPointF(21, 18))
        else:
            painter.drawArc(QRectF(15, 9, 10, 12), -60 * 16, 120 * 16)
            if self._level >= 50:
                painter.drawArc(QRectF(13, 6, 16, 18), -60 * 16, 120 * 16)
        painter.end()


class PlayerBar(QFrame):
    next_requested = Signal()
    prev_requested = Signal()
    title_clicked = Signal()
    queue_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PlayerBar")
        self.setFixedHeight(80)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.7)
        self._route = FollowDefaultOutput(self._player, self._audio, self)
        self._route.errorOccurred.connect(
            lambda message: audio_error_dialog(self, message))
        self._current: Path | None = None
        self._seeking = False
        self._last_volume = 70
        self._muted = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 6, 18, 8)
        outer.setSpacing(2)

        # -- thin top row: title + artist ---------------------------------
        top = QHBoxLayout()
        top.setSpacing(10)
        self.title = QPushButton("未在播放")
        self.title.setObjectName("PlayerTitle")
        self.title.setFlat(True)
        self.title.setCursor(Qt.PointingHandCursor)
        self.title.setFocusPolicy(Qt.NoFocus)
        self.title.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; }")
        self.title.clicked.connect(self.title_clicked.emit)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("PlayerSubtitle")
        self.subtitle.setStyleSheet(
            f"background: transparent; color:{theme.TEXT_FAINT}; font-size:11px;")
        top.addWidget(self.title)
        top.addWidget(self.subtitle)
        top.addStretch(1)
        outer.addLayout(top)

        # -- controls row: transport/time/progress hug the left -----------
        row = QHBoxLayout()
        row.setSpacing(12)

        self.prev_btn = QPushButton()
        self.play_btn = QPushButton()
        self.next_btn = QPushButton()
        style = self.style()
        self.prev_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_MediaSkipBackward))
        self.play_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_MediaPlay))
        self.next_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_MediaSkipForward))
        for button in (self.prev_btn, self.play_btn, self.next_btn):
            button.setFixedSize(30, 28)
            button.setObjectName("TransportButton")
            button.setFocusPolicy(Qt.NoFocus)
            row.addWidget(button)

        self.time = QLabel("0:00 / 0:00")
        self.time.setObjectName("PlayerTime")
        self.time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time.setFixedWidth(84)
        row.addWidget(self.time)

        self.progress = QSlider(Qt.Horizontal)
        self.progress.setObjectName("Progress")
        self.progress.setRange(0, 1000)
        self.progress.setFocusPolicy(Qt.NoFocus)
        self.progress.setMinimumWidth(260)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(self.progress, 1)
        # a short gap keeps the two groups apart without stranding the bar
        row.addSpacing(28)

        # -- right group: volume + queue ----------------------------------
        self.volume_btn = VolumeButton()
        self.volume_btn.clicked.connect(self.toggle_mute)
        row.addWidget(self.volume_btn, 0, Qt.AlignRight)

        self.volume = QSlider(Qt.Horizontal)
        self.volume.setObjectName("Volume")
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        self.volume.setFixedWidth(84)
        self.volume.setFocusPolicy(Qt.NoFocus)
        row.addWidget(self.volume, 0, Qt.AlignRight)

        self.queue_btn = QPushButton()
        self.queue_btn.setObjectName("TransportButton")
        self.queue_btn.setIcon(outline_icon("playlist"))
        self.queue_btn.setIconSize(QSize(18, 18))
        self.queue_btn.setFixedSize(30, 28)
        self.queue_btn.setToolTip("播放列表")
        self.queue_btn.setCursor(Qt.PointingHandCursor)
        self.queue_btn.setFocusPolicy(Qt.NoFocus)
        self.queue_btn.clicked.connect(self.queue_clicked.emit)
        row.addWidget(self.queue_btn, 0, Qt.AlignRight)

        outer.addLayout(row)

        self.play_btn.clicked.connect(self.toggle)
        self.prev_btn.clicked.connect(self.prev_requested.emit)
        self.next_btn.clicked.connect(self.next_requested.emit)
        self.volume.valueChanged.connect(self._on_volume)
        self.progress.sliderPressed.connect(self._on_seek_start)
        self.progress.sliderReleased.connect(self._on_seek_end)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self.volume_btn.set_level(70, False)

    # -- public -----------------------------------------------------------

    def play_file(self, path: Path, title: str = "", subtitle: str = "") -> None:
        self._current = path
        self.title.setText(title or path.stem)
        self.subtitle.setText(subtitle)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    @property
    def current_path(self) -> Path | None:
        return self._current

    @property
    def media_player(self):
        return self._player

    def toggle(self) -> None:
        if self._current is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def toggle_mute(self) -> None:
        if self._muted:
            self._muted = False
            self.volume.setValue(self._last_volume or 70)
        else:
            self._last_volume = self.volume.value() or 70
            self._muted = True
            self.volume.setValue(0)
        self.volume_btn.set_level(self._last_volume, self._muted)

    def stop(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        self._current = None
        self.title.setText("未在播放")
        self.subtitle.setText("")
        self.progress.setValue(0)
        self.time.setText("0:00 / 0:00")

    # -- slots ------------------------------------------------------------

    def _on_volume(self, value: int) -> None:
        if value > 0:
            self._last_volume = value
            self._muted = False
        self._audio.setVolume(value / 100)
        self.volume_btn.set_level(value, self._muted)
        self.volume.setToolTip(f"音量 {value}%")

    def _on_seek_start(self) -> None:
        self._seeking = True

    def _on_seek_end(self) -> None:
        self._seeking = False
        if self._player.duration() > 0:
            self._player.setPosition(int(self._player.duration() * self.progress.value() / 1000))

    def _on_position(self, value: int) -> None:
        if not self._seeking and self._player.duration() > 0:
            self.progress.setValue(int(value / self._player.duration() * 1000))
        self.time.setText(f"{_fmt(value)} / {_fmt(self._player.duration())}")

    def _on_duration(self, value: int) -> None:
        self.time.setText(f"{_fmt(self._player.position())} / {_fmt(value)}")

    def _on_state(self, state) -> None:
        style = self.style()
        pixmap = (style.StandardPixmap.SP_MediaPause if state == QMediaPlayer.PlayingState
                  else style.StandardPixmap.SP_MediaPlay)
        self.play_btn.setIcon(style.standardIcon(pixmap))
