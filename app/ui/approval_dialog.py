"""Manual approval dialog.

Shows every candidate the channels produced, marks which rule each one failed, lets
the user audition before deciding, and can force-download a specific candidate.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..config import load_config, path_setting
from ..core.channels.base import Candidate
from ..core.download import download_chosen
from ..core.match import match_candidate
from ..db.store import Store
from . import theme

COLUMNS = ["来源", "标题", "艺术家", "专辑", "时长", "音质", "大小", "校验"]


class ApprovalDialog(QDialog):
    def __init__(self, store: Store, song_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("待确认")
        self.resize(980, 520)
        self.store = store
        self.song_id = song_id
        self.config = load_config()

        self.track = store.get_track(song_id)
        self.record = store.approval_for(song_id)
        self.candidates = []
        if self.record is not None:
            import json

            self.candidates = [Candidate.from_record(item)
                               for item in json.loads(self.record["candidates_json"])]

        layout = QVBoxLayout(self)

        head = QLabel(
            f"<b>{self.track['title']}</b><br>"
            f"<span style='color:{theme.TEXT_DIM}'>{self.track['artist']} · "
            f"{self.track['album']} · {_duration(self.track['duration_ms'])}</span>"
        )
        head.setTextFormat(Qt.RichText)
        layout.addWidget(head)

        self.table = QTableWidget(len(self.candidates), len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, candidate in enumerate(self.candidates):
            self._fill_row(row, candidate)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.preview_btn = QPushButton("试听选中")
        self.preview_btn.clicked.connect(self._preview)
        self.accept_btn = QPushButton("用选中候选入库")
        self.accept_btn.setObjectName("Accent")
        self.accept_btn.clicked.connect(self._accept)
        self.reject_btn = QPushButton("拒绝（不再自动重试）")
        self.reject_btn.clicked.connect(self._reject)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        actions.addWidget(self.preview_btn)
        actions.addWidget(self.accept_btn)
        actions.addWidget(self.reject_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.7)

    # -- table ------------------------------------------------------------

    def _fill_row(self, row: int, candidate: Candidate) -> None:
        match = match_candidate(
            {"title": self.track["title"], "artist": self.track["artist"],
             "album": self.track["album"], "duration_ms": self.track["duration_ms"]},
            {"title": candidate.title, "artist": candidate.artist,
             "album": candidate.album, "duration_ms": candidate.duration_ms},
        )
        values = [
            f"{candidate.channel}" + (f"/{candidate.raw.get('script_name')}" if candidate.raw.get('script_name') else ""),
            candidate.title,
            candidate.artist,
            candidate.album,
            _duration(candidate.duration_ms),
            candidate.quality,
            _size(candidate.size_bytes),
            "全部通过" if match.passed else "未通过: " + "、".join(match.failed_rules()),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value or ""))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if column == 7:
                item.setForeground(Qt.GlobalColor.green if match.passed else Qt.GlobalColor.yellow)
            self.table.setItem(row, column, item)

    def _selected(self) -> Candidate | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.candidates):
            return self.candidates[row]
        return None

    # -- actions ----------------------------------------------------------

    def _preview(self) -> None:
        candidate = self._selected()
        if candidate is None or not candidate.url:
            QMessageBox.information(self, "没有可试听的候选", "请选择一行带链接的候选。")
            return
        self._player.setSource(QUrl(candidate.url))
        self._player.play()

    def _accept(self) -> None:
        candidate = self._selected()
        if candidate is None or not candidate.url:
            QMessageBox.information(self, "没有候选", "请选择一行。")
            return
        floor = str(self.config["quality"].get("floor_after_approval", "320k")).lower()
        ranks = {"hires": 4, "lossless": 3, "flac": 3, "320k": 2, "192k": 1, "128k": 0}
        floor_rank = ranks.get(floor, 2)
        if ranks.get((candidate.quality or "").lower(), -1) < floor_rank:
            QMessageBox.warning(
                self, "低于授权下限",
                f"当前候选是 {candidate.quality or '未知音质'}，低于设置里的"
                f"「{floor}」。请改选更高音质，或先在设置里调整下限。")
            return
        self._player.stop()
        path, message = download_chosen(
            self.track, candidate, self.store,
            library=path_setting(self.config, "library"),
            staging=path_setting(self.config, "staging"),
            lyric_fetcher=None,
            expected_lossless=False,
            min_bitrate=float(self.config["quality"].get("min_lossless_bitrate", 400)),
            manual_bitrate=float(self.config["quality"].get("manual_lossless_bitrate", 600)),
        )
        if path is None:
            QMessageBox.warning(self, "入库失败", message)
            return
        if self.record is not None:
            self.store.decide_approval(int(self.record["id"]), "accepted", message)
        QMessageBox.information(self, "已入库", f"{path.name}\n{message}")
        self.accept()

    def _reject(self) -> None:
        self.store.set_state(self.song_id, "match_failed")
        if self.record is not None:
            self.store.decide_approval(int(self.record["id"]), "rejected", "人工拒绝")
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._player.stop()
        super().closeEvent(event)


def _duration(value) -> str:
    if not value:
        return ""
    seconds = int(value) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def _size(value) -> str:
    if not value:
        return ""
    return f"{value / 1048576:.1f} MB"
