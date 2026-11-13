"""Keep a QMediaPlayer on the current Windows default audio endpoint.

Qt creates a QAudioOutput against the default device at construction time.  If the
user plugs in headphones or changes the default endpoint afterwards, the existing
output object keeps playing to the old device.  This helper watches
QMediaDevices.audioOutputsChanged and rebinds the player, preserving source,
position, volume, mute and playback state.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from .messagebox import QMessageBox


class FollowDefaultOutput(QObject):
    errorOccurred = Signal(str)

    def __init__(self, player: QMediaPlayer, audio: QAudioOutput, parent=None):
        super().__init__(parent or player)
        self._player = player
        self._audio = audio
        self._devices = QMediaDevices(self)
        self._rebinding = False

        device = QMediaDevices.defaultAudioOutput()
        if not device.isNull():
            self._audio.setDevice(device)
        self._devices.audioOutputsChanged.connect(self._on_outputs_changed)
        self._player.errorOccurred.connect(self._on_error)

    def _on_outputs_changed(self) -> None:
        if self._rebinding:
            return
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            return
        current = self._audio.device()
        if not current.isNull() and current.id() == device.id():
            return
        self._rebind(device)

    def _rebind(self, device) -> None:
        was_playing = self._player.playbackState() == QMediaPlayer.PlayingState
        was_paused = self._player.playbackState() == QMediaPlayer.PausedState
        position = self._player.position()
        source = self._player.source()
        volume = self._audio.volume()
        muted = self._audio.isMuted()

        self._rebinding = True
        try:
            self._player.setAudioOutput(None)
            old = self._audio
            new = QAudioOutput(self._player)
            new.setDevice(device)
            new.setVolume(volume)
            new.setMuted(muted)
            self._player.setAudioOutput(new)
            self._audio = new
            old.deleteLater()

            if not source.isEmpty():
                self._player.setSource(source)
                self._player.setPosition(position)
                if was_playing:
                    self._player.play()
                elif was_paused:
                    self._player.play()
                    self._player.pause()
        finally:
            self._rebinding = False

    def _on_error(self, _error, message: str) -> None:
        if message:
            self.errorOccurred.emit(message)


def audio_error_dialog(parent, message: str) -> None:
    QMessageBox.warning(parent, "音频输出失败", message)
