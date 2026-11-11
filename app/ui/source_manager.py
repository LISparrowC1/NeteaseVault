"""Source-script manager: import, enable/disable, and health-check LX sources.

Everything that talks to the Node engine runs in a worker thread; loading a dozen
obfuscated scripts takes several seconds and must never freeze the window.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..config import engine_dir, load_config
from ..core.channels.source_channel import music_info
from ..core.engine_client import EngineClient
from ..db.store import Store
from . import theme
from .workers import Worker


class SourceManagerDialog(QDialog):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自定义源管理")
        self.resize(880, 500)
        self.store = store
        self.config = load_config()
        self.engine = EngineClient(engine_dir())
        self.rows: list[dict] = []
        self._worker: Worker | None = None

        layout = QVBoxLayout(self)
        self.scripts_dir = self.engine.user_scripts_dir
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        note = QLabel(
            "源脚本放在：\n"
            f"{self.scripts_dir}\n"
            "也可以点下面的「导入源脚本…」直接选择 .js 文件，导入后重启程序即可生效。")
        note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        note.setStyleSheet(f"color:{theme.TEXT_DIM};")
        layout.addWidget(note)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["文件", "名称", "版本", "支持的源", "启用", "健康检查"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.TEXT_FAINT};")
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.reload)
        self.import_btn = QPushButton("导入源脚本…")
        self.import_btn.clicked.connect(self._import)
        self.health_btn = QPushButton("全部健康检查")
        self.health_btn.setObjectName("Accent")
        self.health_btn.clicked.connect(self._health)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.import_btn)
        row.addWidget(self.health_btn)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)

        self.reload()

    # -- loading ----------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = "") -> None:
        for button in (self.refresh_btn, self.import_btn, self.health_btn):
            button.setEnabled(not busy)
        self.status.setText(message)

    def reload(self) -> None:
        self._set_busy(True, "正在加载源脚本（首次加载需要几秒）…")
        self._worker = Worker(lambda: self.engine.call("scripts", timeout=120))
        self._worker.finished_ok.connect(self._populate)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _populate(self, scripts: list) -> None:
        states = self.store.script_state()
        self.rows = []
        self.table.setRowCount(len(scripts))
        for index, item in enumerate(scripts):
            file_path = item["file"]
            if file_path not in states:
                self.store.upsert_script(file_path, name=item.get("name") or "",
                                         version=item.get("version") or "",
                                         sources=item.get("sources") or {})
                states[file_path] = {"enabled": 1}
            self.rows.append({"file": file_path, "name": item.get("name") or "",
                              "sources": item.get("sources") or {},
                              "error": item.get("error")})
            quality = sorted({q for info in (item.get("sources") or {}).values()
                              for q in (info.get("qualitys") or [])})
            values = [
                file_path,
                item.get("name") or "-",
                item.get("version") or "-",
                ",".join((item.get("sources") or {}).keys()),
                "是" if states[file_path].get("enabled", 1) else "否",
                "加载失败" if item.get("error") else (",".join(quality) or "-"),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(index, column, cell)
        self._set_busy(False, f"共 {len(scripts)} 个脚本")

    def _on_error(self, message: str) -> None:
        self._set_busy(False, "加载失败")
        QMessageBox.critical(self, "引擎错误", message)

    # -- actions ----------------------------------------------------------

    def _import(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择源脚本", "", "JavaScript (*.js)")
        if not files:
            return
        target = self.scripts_dir
        target.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copy2(path, target / Path(path).name)
        QMessageBox.information(self, "已导入", f"复制 {len(files)} 个脚本，正在重新加载。")
        self.reload()

    def _health(self) -> None:
        rows = self.store.list_tracks()
        sample = next((row for row in rows if row["cloud_playable"]), None)
        if sample is None:
            QMessageBox.warning(self, "没有样本", "库里还没有可用于测试的歌曲。")
            return
        info = music_info(sample)
        targets = [row for row in self.rows
                   if not row.get("error") and "wy" in (row.get("sources") or {})]
        if not targets:
            QMessageBox.information(self, "没有可检查的源", "当前没有支持网易云的脚本。")
            return

        self._set_busy(True, "正在逐个检查…")

        def work():
            results = []
            for row in targets:
                qualities = row["sources"]["wy"].get("qualitys") or []
                quality = "flac" if "flac" in qualities else (qualities[0] if qualities else "")
                started = time.monotonic()
                try:
                    self.engine.call("resolve", {"file": row["file"], "source": "wy",
                                                 "quality": quality, "musicInfo": info}, timeout=40)
                    results.append((row["file"], True, int((time.monotonic() - started) * 1000), ""))
                except Exception as exc:
                    results.append((row["file"], False, int((time.monotonic() - started) * 1000),
                                    str(exc)[:120]))
            return results

        self._worker = Worker(work)
        self._worker.finished_ok.connect(self._on_health_done)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_health_done(self, results: list) -> None:
        index_by_file = {row["file"]: i for i, row in enumerate(self.rows)}
        for file_path, ok, latency, note in results:
            self.store.record_health(file_path, ok, latency, note)
            index = index_by_file.get(file_path)
            if index is None or self.table.item(index, 5) is None:
                continue
            self.table.item(index, 5).setText(f"OK {latency}ms" if ok else "失败")
            self.table.item(index, 5).setForeground(Qt.green if ok else Qt.yellow)
        ok_count = sum(1 for _, ok, _, _ in results if ok)
        self._set_busy(False, f"健康检查完成：{ok_count}/{len(results)} 可用")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.engine.close()
        super().closeEvent(event)
