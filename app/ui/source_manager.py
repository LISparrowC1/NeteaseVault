"""Source-script manager: import, enable/disable, and health-check LX sources.

Everything that talks to the Node engine runs in a worker thread; loading a dozen
obfuscated scripts takes several seconds and must never freeze the window.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..config import engine_dir, load_config
from ..core import source_fetcher
from ..core.channels.source_channel import music_info
from ..core.engine_client import EngineClient
from ..core.netease import NeteaseClient
from ..db.store import Store
from . import theme
from .messagebox import QMessageBox
from .workers import Worker


class SourceManagerDialog(QDialog):
    def __init__(self, store: Store, parent=None, credentials=None):
        super().__init__(parent)
        self.setWindowTitle("自定义源管理")
        self.resize(880, 500)
        self.store = store
        self.credentials = credentials
        self.config = load_config()
        self.engine = EngineClient(engine_dir())
        self.rows: list[dict] = []
        self._worker: Worker | None = None
        self._cleaning = False

        layout = QVBoxLayout(self)
        self.scripts_dir = self.engine.user_scripts_dir
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        note = QLabel(
            "源脚本放在：\n"
            f"{self.scripts_dir}\n"
            "也可以点下面的「导入源脚本…」直接选择 .js 文件，导入后重启程序即可生效。\n"
            f"自动获取的仓库列表：{source_fetcher.spec_path()}")
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
        self.fetch_btn = QPushButton("自动获取最新音源")
        self.fetch_btn.clicked.connect(self._auto_fetch)
        self.spec_btn = QPushButton("编辑源地址列表")
        self.spec_btn.clicked.connect(self._edit_spec)
        self.up_btn = QPushButton("上移")
        self.up_btn.clicked.connect(lambda: self._move_script(-1))
        self.down_btn = QPushButton("下移")
        self.down_btn.clicked.connect(lambda: self._move_script(1))
        self.health_btn = QPushButton("全部健康检查")
        self.health_btn.setObjectName("Accent")
        self.health_btn.clicked.connect(self._health)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.import_btn)
        row.addWidget(self.fetch_btn)
        row.addWidget(self.spec_btn)
        row.addWidget(self.up_btn)
        row.addWidget(self.down_btn)
        row.addWidget(self.health_btn)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)

        self.finished.connect(self._cleanup)
        self._drop_internal_shim()
        self.reload()

    # -- loading ----------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = "") -> None:
        for button in (self.refresh_btn, self.import_btn, self.fetch_btn,
                       self.up_btn, self.down_btn, self.health_btn):
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
        next_priority = max((int(row.get("priority") or 0) for row in states.values()),
                            default=-1) + 1
        ordered = []
        for item in scripts:
            file_path = item["file"]
            if file_path not in states:
                self.store.upsert_script(
                    file_path, name=item.get("name") or "",
                    version=item.get("version") or "",
                    priority=next_priority, sources=item.get("sources") or {})
                states[file_path] = {"enabled": 1, "priority": next_priority}
                next_priority += 1
            priority = int(states[file_path].get("priority") or 0)
            quality = sorted({q for info in (item.get("sources") or {}).values()
                              for q in (info.get("qualitys") or [])})
            ordered.append((priority, item, quality))
        ordered.sort(key=lambda entry: entry[0])
        self.rows = []
        self.table.setRowCount(len(ordered))
        for index, (_priority, item, quality) in enumerate(ordered):
            file_path = item["file"]
            self.rows.append({"file": file_path, "name": item.get("name") or "",
                              "version": item.get("version") or "",
                              "sources": item.get("sources") or {},
                              "quality": quality, "error": item.get("error")})
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

    def _move_script(self, delta: int) -> None:
        row = self.table.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < len(self.rows):
            return
        for column in range(self.table.columnCount()):
            first = self.table.takeItem(row, column)
            second = self.table.takeItem(target, column)
            self.table.setItem(row, column, second)
            self.table.setItem(target, column, first)
        self.rows[row], self.rows[target] = self.rows[target], self.rows[row]
        self.store.set_script_priorities([entry["file"] for entry in self.rows])
        self.table.selectRow(target)

    def _on_error(self, message: str) -> None:
        self._set_busy(False, "加载失败")
        QMessageBox.critical(self, "引擎错误", message)

    # -- actions ----------------------------------------------------------

    def _drop_internal_shim(self) -> None:
        """Remove a copy of the bundled host shim mistaken for a source script."""
        bundled = engine_dir() / "host" / "lx-shim.js"
        candidate = self.scripts_dir / "lx-shim.js"
        try:
            if (candidate.exists() and bundled.exists()
                    and candidate.read_bytes() == bundled.read_bytes()):
                candidate.unlink()
        except OSError:
            pass

    @staticmethod
    def _looks_like_source(path: Path, text: str) -> bool:
        if path.name.lower() == "lx-shim.js":
            return False
        return source_fetcher.is_source(text)

    def _import(self) -> None:
        start = (QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
                 or str(Path.home()))
        files, _ = QFileDialog.getOpenFileNames(self, "选择源脚本", start,
                                                "JavaScript (*.js)")
        if not files:
            return
        invalid = []
        for path in files:
            try:
                text = Path(path).read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                invalid.append(Path(path).name)
                continue
            if not self._looks_like_source(Path(path), text):
                invalid.append(Path(path).name)
        if invalid:
            QMessageBox.warning(
                self, "不是音源脚本",
                "以下文件不是 LX 音源脚本，已停止导入：\n"
                + "\n".join(invalid)
                + "\n\n请选择带有 @name 和 lx.send('inited', ...) 的源脚本。")
            return
        target = self.scripts_dir
        target.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copy2(path, target / Path(path).name)
        self.engine.close()
        QMessageBox.information(self, "已导入", f"复制 {len(files)} 个脚本，正在重新加载。")
        self.reload()

    def _edit_spec(self) -> None:
        path = source_fetcher.ensure_spec_file()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _auto_fetch(self) -> None:
        if self.credentials is None or not self.credentials.has_cookie():
            QMessageBox.warning(self, "未登录", "自动更新音源需要登录后取真实云端样本。")
            return
        self._set_busy(True, "正在从 GitHub 获取最新音源…")
        worker = Worker(lambda: self._do_auto_fetch(
            lambda message: worker.progress.emit(message)))
        worker.progress.connect(self.status.setText)
        worker.finished_ok.connect(self._on_auto_fetch_done)
        worker.failed.connect(self._on_error)
        self._worker = worker
        worker.start()

    def _do_auto_fetch(self, progress) -> list[str]:
        candidates = source_fetcher.fetch_candidates(progress)
        if not candidates:
            return []
        return source_fetcher.install_candidates(
            candidates, self.credentials.load_cookie(), self.store.db_path,
            self.scripts_dir, progress)

    def _on_auto_fetch_done(self, names: list) -> None:
        self.engine.close()
        self.reload()
        if not names:
            QMessageBox.warning(
                self, "没有可用音源",
                "从各仓库拉取的脚本都没有通过真实歌曲解析测试，已保留原有音源。")
            return
        QMessageBox.information(
            self, "音源已更新",
            "已启用以下通过测试的音源：\n" + "\n".join(names))

    def _health(self) -> None:
        targets = [row for row in self.rows
                   if not row.get("error") and "wy" in (row.get("sources") or {})]
        if not targets:
            QMessageBox.information(self, "没有可检查的源", "当前没有支持网易云的脚本。")
            return
        if self.credentials is None or not self.credentials.has_cookie():
            QMessageBox.warning(self, "未登录", "健康检查需要登录后从云端歌单取样本。")
            return

        self._set_busy(True, "正在从云端「我喜欢的音乐」取样本…")

        def work():
            client = NeteaseClient(self.credentials.load_cookie(), min_interval=1.2)
            profile = client.account()
            playlist_id = client.liked_playlist_id(int(profile["userId"]))
            entries = client.playlist_track_ids(playlist_id)
            if not entries:
                raise RuntimeError("「我喜欢的音乐」为空，无法取样本")

            probe = Store(self.store.db_path)
            try:
                existing = probe.existing_track_ids()
            finally:
                probe.close()

            def downloaded(entry) -> bool:
                row = existing.get(int(entry["id"]))
                return bool(row and row["local_rel_path"])

            chosen = next((entry for entry in entries if not downloaded(entry)), entries[0])
            details = client.songs_detail([chosen["id"]])
            if not details:
                raise RuntimeError("云端没有返回样本歌曲详情")
            song = details[0]
            info = music_info({
                "song_id": int(song["id"]),
                "title": song.get("name"),
                "artist": "、".join(a.get("name", "") for a in (song.get("ar") or [])),
                "album": (song.get("al") or {}).get("name"),
                "duration_ms": song.get("dt"),
            })

            results = []
            for row in targets:
                qualities = row["sources"]["wy"].get("qualitys") or []
                quality = "flac" if "flac" in qualities else (qualities[0] if qualities else "")
                started = time.monotonic()
                try:
                    self.engine.call("resolve", {"file": row["file"], "source": "wy",
                                                 "quality": quality, "musicInfo": info}, timeout=40)
                    results.append((row["file"], True,
                                    int((time.monotonic() - started) * 1000), ""))
                except Exception as exc:
                    results.append((row["file"], False,
                                    int((time.monotonic() - started) * 1000),
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
            cell = self.table.item(index, 5)
            cell.setText(f"OK {latency}ms" if ok else "失败")
            cell.setToolTip(note or ("可用" if ok else "解析失败"))
            cell.setForeground(Qt.green if ok else Qt.yellow)
        ok_count = sum(1 for _, ok, _, _ in results if ok)
        self._set_busy(False, f"健康检查完成：{ok_count}/{len(results)} 可用")

    def _cleanup(self, *_args) -> None:
        if self._cleaning:
            return
        self._cleaning = True
        worker = self._worker
        if worker is not None and worker.isRunning():
            self.engine.shutdown()
            if not worker.wait(10000):
                worker.terminate()
                worker.wait(1000)
        self.engine.shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cleanup()
        super().closeEvent(event)
