"""Settings dialog. Every tunable from docs/方案.md 11 lives here."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QPushButton, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from ..config import save_config

CHANNEL_LABELS = {"musicdl": "musicdl", "source": "自定义源", "official": "官方接口"}


class SettingsDialog(QDialog):
    def __init__(self, config: dict, store=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(620, 460)
        self.config = config
        self.store = store

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._paths_tab(), "路径")
        tabs.addTab(self._download_tab(), "下载")
        tabs.addTab(self._rate_tab(), "节奏与音质")
        tabs.addTab(self._cache_tab(), "缓存")
        tabs.addTab(self._sources_tab(), "自定义源")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- tabs -------------------------------------------------------------

    def _paths_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.library_edit = QLineEdit(self.config["paths"]["library"])
        self.staging_edit = QLineEdit(self.config["paths"]["staging"])
        self.usb_edit = QLineEdit(self.config["paths"]["usb_target"])
        form.addRow("正式库目录", self.library_edit)
        form.addRow("暂存区目录", self.staging_edit)
        form.addRow("U 盘目标", self.usb_edit)
        note = QLabel("相对路径以程序所在目录为基准。")
        note.setStyleSheet("color:#8A8F98;")
        form.addRow("", note)

        row = QHBoxLayout()
        usb_btn = QPushButton("立即同步到 U 盘")
        usb_btn.clicked.connect(self._sync_usb)
        playlist_btn = QPushButton("生成播放列表")
        playlist_btn.clicked.connect(self._write_playlist)
        row.addWidget(usb_btn)
        row.addWidget(playlist_btn)
        row.addStretch(1)
        form.addRow("", row)
        return page

    def _library(self):
        from ..config import app_root

        value = self.library_edit.text().strip() or "library"
        path = Path(value)
        return path if path.is_absolute() else app_root() / path

    def _sync_usb(self) -> None:
        from ..core.usb import sync_to_usb

        target_text = self.usb_edit.text().strip()
        if not target_text:
            QMessageBox.warning(self, "未设置目标", "请先填写 U 盘目标目录。")
            return
        target = Path(target_text)
        try:
            report = sync_to_usb(self._library(), target)
        except Exception as exc:
            QMessageBox.critical(self, "同步失败", str(exc))
            return
        QMessageBox.information(self, "完成", report.as_line())

    def _write_playlist(self) -> None:
        from ..core.usb import write_playlist

        if self.store is None:
            return
        target_text = self.usb_edit.text().strip()
        if not target_text:
            QMessageBox.warning(self, "未设置目标", "请先填写 U 盘目标目录。")
            return
        rows = self.store.list_tracks()
        destination = Path(target_text) / "我喜欢的音乐.m3u8"
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            count = write_playlist(self._library(), destination, rows)
        except Exception as exc:
            QMessageBox.critical(self, "生成失败", str(exc))
            return
        QMessageBox.information(self, "完成", f"已写入 {count} 首到 {destination}")

    def _download_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("下载通道顺序（从上到下依次尝试）"))
        self.order_list = QListWidget()
        for name in self.config["download"]["order"]:
            self.order_list.addItem(name)
        layout.addWidget(self.order_list, 1)

        row = QHBoxLayout()
        up = QPushButton("上移")
        down = QPushButton("下移")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        row.addWidget(up)
        row.addWidget(down)
        row.addStretch(1)
        layout.addLayout(row)

        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 8)
        self.concurrency.setValue(int(self.config["download"]["concurrency"]))
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setValue(int(self.config["download"]["retries"]))
        form = QFormLayout()
        form.addRow("下载并发", self.concurrency)
        form.addRow("同源重试次数", self.retries)
        layout.addLayout(form)
        return page

    def _rate_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.2, 10.0)
        self.interval.setSingleStep(0.1)
        self.interval.setValue(float(self.config["rate"]["search_interval_s"]))
        self.window = QSpinBox()
        self.window.setRange(1, 120)
        self.window.setValue(int(self.config["rate"]["search_window_per_min"]))
        self.floor = QLineEdit(self.config["quality"]["floor_after_approval"])
        self.min_bitrate = QSpinBox()
        self.min_bitrate.setRange(100, 2000)
        self.min_bitrate.setValue(int(self.config["quality"]["min_lossless_bitrate"]))
        form.addRow("搜索最小间隔（秒）", self.interval)
        form.addRow("搜索窗口（次/分钟）", self.window)
        form.addRow("人工授权后最高音质", self.floor)
        form.addRow("无损最低平均码率（kbps）", self.min_bitrate)
        return page

    def _cache_tab(self) -> QWidget:
        from ..core import covers

        page = QWidget()
        form = QFormLayout(page)
        count, size = covers.cache_size()
        self.cache_path_label = QLabel(str(covers.cache_dir()))
        self.cache_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.cache_info_label = QLabel(f"{count} 个文件，{size / 1048576:.1f} MB")
        clear = QPushButton("清除缓存")
        clear.clicked.connect(self._clear_cache)
        form.addRow("封面缓存目录", self.cache_path_label)
        form.addRow("当前占用", self.cache_info_label)
        note = QLabel("清除封面缓存、暂存区残留与 musicdl 输出文件；不会动音乐库。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8A8F98;")
        form.addRow("", note)
        form.addRow("", clear)
        return page

    def _clear_cache(self) -> None:
        from ..core import covers

        freed = covers.clear()
        count, size = covers.cache_size()
        self.cache_info_label.setText(f"{count} 个文件，{size / 1048576:.1f} MB")
        QMessageBox.information(self, "已清除", f"释放 {freed / 1048576:.1f} MB")

    def _sources_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        note = QLabel("自定义音源用于补充官方接口拿不到的歌曲。\n"
                      "源脚本按表格顺序依次尝试，可以在管理窗口里导入、启用或调整顺序。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8A8F98;")
        layout.addWidget(note)
        button = QPushButton("打开自定义源管理…")
        button.clicked.connect(self._open_sources)
        layout.addWidget(button)
        layout.addStretch(1)
        return page

    def _open_sources(self) -> None:
        from .source_manager import SourceManagerDialog

        SourceManagerDialog(self.store, self).exec()

    # -- helpers ----------------------------------------------------------

    def _move(self, delta: int) -> None:
        row = self.order_list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.order_list.count():
            return
        item = self.order_list.takeItem(row)
        self.order_list.insertItem(target, item)
        self.order_list.setCurrentRow(target)

    def _save(self) -> None:
        order = [self.order_list.item(i).text() for i in range(self.order_list.count())]
        if not order:
            QMessageBox.warning(self, "顺序不能为空", "至少保留一个下载通道。")
            return
        self.config["paths"]["library"] = self.library_edit.text().strip() or "library"
        self.config["paths"]["staging"] = self.staging_edit.text().strip() or "staging"
        self.config["paths"]["usb_target"] = self.usb_edit.text().strip()
        self.config["download"]["order"] = order
        self.config["download"]["concurrency"] = self.concurrency.value()
        self.config["download"]["retries"] = self.retries.value()
        self.config["rate"]["search_interval_s"] = self.interval.value()
        self.config["rate"]["search_window_per_min"] = self.window.value()
        self.config["quality"]["floor_after_approval"] = self.floor.text().strip() or "320k"
        self.config["quality"]["min_lossless_bitrate"] = self.min_bitrate.value()
        save_config(self.config)
        self.accept()
