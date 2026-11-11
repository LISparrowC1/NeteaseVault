"""Main window.

Three visual layers share the bottom player bar:

* the list page (sidebar + header + track list)
* a slide-out play queue on the right of the list
* a full-page now-playing view with scrolling lyrics

List membership is derived from two independent axes (app/core/states.py); a file on
disk with no cloud record shows up as 「本地」.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..config import app_root, engine_dir, load_config, path_setting
from ..core import states
from ..version import __version__
from ..core.library_scan import reconcile_local
from ..core.netease import NeteaseClient
from ..core.sync import sync_liked
from ..db.store import Store
from ..security import CredentialStore
from .account_dialog import AccountDialog
from .login_dialog import LoginDialog
from .appicon import app_icon
from .icons import LIST_ICONS, outline_icon
from .models import TrackDelegate, TrackModel
from .now_playing import NowPlayingPage
from .player_bar import PlayerBar
from .settings_dialog import SettingsDialog

try:
    from send2trash import send2trash
except ImportError:  # pragma: no cover
    send2trash = None


def _recycle(path: Path) -> None:
    if not path.exists():
        return
    if send2trash is not None:
        send2trash(str(path))
    else:
        path.unlink()


# -- workers --------------------------------------------------------------

class SyncWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path: Path, cookie: str):
        super().__init__()
        self._db_path, self._cookie = db_path, cookie

    def run(self) -> None:
        try:
            client = NeteaseClient(self._cookie, min_interval=1.5)
            store = Store(self._db_path)
            try:
                profile = client.account()
                report = sync_liked(client, store)
                store.set_meta("account_uid", str(profile["userId"]))
                store.set_meta("account_nickname", str(profile.get("nickname") or ""))
            finally:
                store.close()
            self.done.emit(report)
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadWorker(QThread):
    track_started = Signal(int, str)
    track_finished = Signal(int, str, str)
    track_progress = Signal(int, float)
    progress = Signal(int, int)
    failed = Signal(str)

    def __init__(self, db_path: Path, song_ids: list[int], config: dict, cookie: str):
        super().__init__()
        self._db_path, self._ids = db_path, list(song_ids)
        self._config, self._cookie = config, cookie
        self._pause = threading.Event()
        self._pause.set()
        self._stop = threading.Event()
        self.cancelled = False

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def stop(self) -> None:
        self.cancelled = True
        self._stop.set()
        self._pause.set()

    def run(self) -> None:
        from ..core.channels.musicdl_channel import MusicdlChannel
        from ..core.channels.official_channel import OfficialChannel
        from ..core.channels.source_channel import SourceChannel
        from ..core.download import process_track
        from ..core.engine_client import EngineClient

        store = None
        try:
            client = NeteaseClient(self._cookie, min_interval=1.5)
            mapping = {
                "musicdl": lambda: MusicdlChannel(self._cookie),
                "source": lambda: SourceChannel(EngineClient(engine_dir())),
                "official": lambda: OfficialChannel(client),
            }
            order = self._config["download"]["order"]
            channels = [mapping[name]() for name in order if name in mapping]
            store = Store(self._db_path)
            library = path_setting(self._config, "library")
            staging = path_setting(self._config, "staging")

            total = len(self._ids)
            for index, song_id in enumerate(self._ids):
                if self._stop.is_set():
                    break
                while not self._pause.is_set() and not self._stop.is_set():
                    time.sleep(0.1)
                if self._stop.is_set():
                    break
                row = store.get_track(song_id)
                if row is None:
                    self.progress.emit(index + 1, total)
                    continue
                self.track_started.emit(song_id, row["title"] or "")
                try:
                    result = process_track(
                        row, channels, store, library=library, staging=staging,
                        lyric_fetcher=client.lyric_text,
                        pause_event=self._pause, cancel_event=self._stop,
                        on_progress=lambda fraction, sid=song_id:
                            self.track_progress.emit(sid, fraction))
                    self.track_finished.emit(song_id, result.status, result.message)
                except Exception as exc:
                    self.track_finished.emit(song_id, "failed", str(exc))
                self.progress.emit(index + 1, total)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if store is not None:
                store.close()


# -- window ---------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"NeteaseVault {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)

        self.config = load_config()
        self.db_path = app_root() / "data" / "library.db"
        self.store = Store(self.db_path)
        self.credentials = CredentialStore(app_root() / "data" / "credentials.bin")
        self.list_key = states.LIST_ALL
        self.queue: list[int] = []          # playback queue, independent of the view
        self.queue_pos = -1
        self._sync_worker: SyncWorker | None = None
        self._download_worker: DownloadWorker | None = None
        self._downloading = False
        self._run_downloaded = 0
        self._run_review = 0

        self._build_ui()
        self._refresh_account_card()
        self._apply_view_state()
        self.reload_tracks()

    # -- layout -----------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_list_page())
        self.now_page = NowPlayingPage()
        self.now_page.back_requested.connect(lambda: self.stack.setCurrentIndex(0))
        self.stack.addWidget(self.now_page)
        root.addWidget(self.stack, 1)

        self.player = PlayerBar()
        self.player.next_requested.connect(lambda: self._step(1))
        self.player.prev_requested.connect(lambda: self._step(-1))
        self.player.title_clicked.connect(self.open_now_playing)
        self.player.queue_clicked.connect(self.toggle_queue)
        root.addWidget(self.player)

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        body = QHBoxLayout(page)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_header())

        centre = QHBoxLayout()
        centre.setContentsMargins(0, 0, 0, 0)
        centre.setSpacing(0)
        self.view = QListView()
        self.model = TrackModel()
        self.view.setModel(self.model)
        self.delegate = TrackDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setMouseTracking(True)
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setUniformItemSizes(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setSelectionMode(QListView.ExtendedSelection)
        self.view.doubleClicked.connect(self._play_index)
        self.view.selectionModel().selectionChanged.connect(
            lambda *_: self._update_download_label())
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        centre.addWidget(self.view, 1)
        centre.addWidget(self._build_queue_panel())
        right.addLayout(centre, 1)

        body.addLayout(right, 1)
        return page

    def _build_sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Sidebar")
        frame.setFixedWidth(200)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(4)

        brand = QLabel("NeteaseVault")
        brand.setObjectName("Brand")
        layout.addWidget(brand)
        layout.addSpacing(8)

        self.account_btn = QPushButton("未登录")
        self.account_btn.setObjectName("AccountCard")
        self.account_btn.setCursor(Qt.PointingHandCursor)
        self.account_btn.clicked.connect(self.open_account)
        layout.addWidget(self.account_btn)
        layout.addSpacing(12)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key in states.LISTS:
            button = QPushButton(states.LIST_LABELS[key])
            button.setObjectName("NavItem")
            button.setCheckable(True)
            button.setChecked(key == self.list_key)
            button.setIcon(outline_icon(LIST_ICONS[key]))
            button.setIconSize(QSize(16, 16))
            button.clicked.connect(lambda _=False, k=key: self.set_list(k))
            layout.addWidget(button)
            self.nav_buttons[key] = button

        layout.addStretch(1)
        settings = QPushButton("设置")
        settings.setObjectName("NavItem")
        settings.clicked.connect(self.open_settings)
        layout.addWidget(settings)
        return frame

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Header")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 14, 24, 12)
        layout.setSpacing(8)

        row = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(2)
        self.title_label = QLabel("我喜欢的音乐")
        self.title_label.setObjectName("PlaylistTitle")
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("PlaylistMeta")
        self.meta_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left.addWidget(self.title_label)
        left.addWidget(self.meta_label)
        row.addLayout(left, 1)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setToolTip("重新扫描本地文件，并核对数据库记录")
        self.refresh_btn.clicked.connect(self.refresh_local)
        self.clear_list_btn = QPushButton("清空当前列表")
        self.clear_list_btn.setToolTip("只清除当前列表的记录")
        self.clear_list_btn.clicked.connect(self.clear_current_list)
        self.clear_sync_btn = QPushButton("清除同步信息")
        self.clear_sync_btn.setToolTip("清除同步带来的歌单/已取消喜欢等信息，保留本地文件")
        self.clear_sync_btn.clicked.connect(self.clear_sync_info)
        self.sync_btn = QPushButton("同步")
        self.sync_btn.clicked.connect(self.start_sync)
        self.download_btn = QPushButton("下载")
        self.download_btn.setObjectName("Accent")
        self.download_btn.setToolTip("下载选中的歌；没选则下载本列表中所有等待下载的歌")
        self.download_btn.clicked.connect(self.start_download)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.cancel_btn = QPushButton("取消下载")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_download)
        for button in (self.refresh_btn, self.clear_list_btn, self.clear_sync_btn,
                       self.sync_btn, self.pause_btn, self.cancel_btn, self.download_btn):
            row.addWidget(button)
        layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setObjectName("DownloadProgress")
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PlaylistMeta")
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
        return frame

    def _build_queue_panel(self) -> QFrame:
        self.queue_panel = QFrame()
        self.queue_panel.setObjectName("QueuePanel")
        self.queue_panel.setFixedWidth(300)
        self.queue_panel.setVisible(False)
        layout = QVBoxLayout(self.queue_panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("播放列表")
        title.setStyleSheet("font-weight:600;")
        head.addWidget(title)
        head.addStretch(1)
        clear = QPushButton("清空")
        clear.setObjectName("NavItem")
        clear.clicked.connect(self.clear_queue)
        head.addWidget(clear)
        close = QPushButton("×")
        close.setObjectName("NavItem")
        close.setFixedWidth(28)
        close.clicked.connect(self.toggle_queue)
        head.addWidget(close)
        layout.addLayout(head)

        self.queue_list = QListWidget()
        self.queue_list.itemDoubleClicked.connect(self._play_queue_item)
        layout.addWidget(self.queue_list, 1)
        return self.queue_panel

    # -- account ----------------------------------------------------------

    def _refresh_account_card(self) -> None:
        nickname = self.store.get_meta("account_nickname") or ""
        if not self.credentials.has_cookie():
            self.account_btn.setText("未登录\n点击登录或设置")
        elif nickname:
            self.account_btn.setText(f"{nickname}\n账户设置")
        else:
            self.account_btn.setText("已保存凭证\n账户设置")

    def open_account(self) -> None:
        AccountDialog(self.credentials, self.store, self).exec()
        self._refresh_account_card()

    def _require_login(self) -> str | None:
        cookie = self.credentials.load_cookie()
        if cookie:
            return cookie
        answer = QMessageBox.question(self, "需要先登录", "还没有登录网易云，无法同步。要现在登录吗？")
        if answer == QMessageBox.Yes and LoginDialog(self.credentials, self).exec():
            self._refresh_account_card()
            return self.credentials.load_cookie()
        return None

    # -- lists ------------------------------------------------------------

    def set_list(self, key: str) -> None:
        self.list_key = key
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)
        self._apply_view_state()
        self.reload_tracks()

    def _apply_view_state(self) -> None:
        """Everything that depends on the current list, in one place.

        Called on startup, on every list switch and after data changes — otherwise
        the first screen disagrees with itself until the user clicks somewhere.
        """
        is_cloud_view = self.list_key == states.LIST_ALL
        self.clear_sync_btn.setVisible(is_cloud_view)
        # 等待下载 and 失效 are derived states; there is nothing to erase there.
        self.clear_list_btn.setVisible(
            self.list_key in (states.LIST_REMOVED, states.LIST_REVIEW,
                              states.LIST_DOWNLOADED, states.LIST_FAILED))
        self._update_download_label()
        self.progress.setVisible(self.list_key == states.LIST_WAITING and self._downloading)
        self.delegate.list_key = self.list_key
        self.view.viewport().update()

    def reload_tracks(self) -> None:
        # Reloads happen on every progress tick; keep the user's selection.
        selected = set(self._selected_ids())
        rows = self.store.list_tracks(self.list_key)
        self.model.set_rows(rows)
        if selected:
            from PySide6.QtCore import QItemSelectionModel

            for index, row in enumerate(rows):
                if int(row["song_id"]) in selected:
                    self.view.selectionModel().select(
                        self.model.index(index), QItemSelectionModel.Select)
        self._queue_ids = [int(row["song_id"]) for row in rows]
        self._update_meta()
        self._apply_view_state()

    def _update_meta(self) -> None:
        # The header describes *the cloud playlist*, not the whole database: a song
        # that left the playlist must stop counting as downloaded here.
        cloud = self.store.list_tracks(states.LIST_ALL)
        downloaded = sum(1 for row in cloud if row["local_state"] == states.DOWNLOADED)
        pending = sum(1 for row in cloud if row["local_state"] == states.PENDING_REVIEW)
        invalid = sum(1 for row in cloud if row["cloud_playable"] == 0)
        last = self.store.last_sync_at()
        last_text = f"上次同步 {last[:16].replace('T', ' ')}" if last else "尚未同步"
        self.meta_label.setText(
            f"云端 {len(cloud)} 首 · 已下载 {downloaded} · 待确认 {pending}"
            f" · 失效 {invalid} · {last_text}")
        self.title_label.setText(states.LIST_TITLES.get(self.list_key, "我喜欢的音乐"))

    # -- local file check -------------------------------------------------

    def refresh_local(self) -> None:
        stats = reconcile_local(self.store, path_setting(self.config, "library"))
        self.reload_tracks()
        parts = []
        if stats["linked"]:
            parts.append(f"关联 {stats['linked']} 首本地文件")
        if stats["orphan"]:
            parts.append(f"{stats['orphan']} 个文件标为「本地」")
        if stats["merged"]:
            parts.append(f"合并 {stats['merged']} 条重复记录")
        if stats["missing"]:
            parts.append(f"{stats['missing']} 首文件已不存在")
        QMessageBox.information(self, "刷新完成", "\n".join(parts) or "没有变化。")

    # -- clearing ---------------------------------------------------------

    def clear_current_list(self) -> None:
        rows = self.store.list_tracks(self.list_key)
        if not rows:
            QMessageBox.information(self, "列表为空", "当前列表没有记录。")
            return
        box = QMessageBox(self)
        box.setWindowTitle(f"清空「{states.LIST_LABELS[self.list_key]}」")
        box.setText(f"将从数据库移除 {len(rows)} 条记录，本地文件默认保留。")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        checkbox = QCheckBox("同时删除本地文件（移到回收站）")
        box.setCheckBox(checkbox)
        if box.exec() != QMessageBox.Yes:
            return
        if checkbox.isChecked():
            library = path_setting(self.config, "library")
            for row in rows:
                if row["local_rel_path"]:
                    _recycle(library / row["local_rel_path"])
        removed = self.store.clear_list(self.list_key)
        self.reload_tracks()
        QMessageBox.information(self, "已清空", f"移除 {removed} 条记录。")

    def clear_sync_info(self) -> None:
        answer = QMessageBox.question(
            self, "清除同步信息",
            "将清空「网易歌单」「已取消喜欢」「失效」等所有由同步带来的信息，"
            "以及同步历史。\n\n本地音乐文件不会删除；有文件的歌会保留并标记为「本地」。\n\n继续吗？")
        if answer != QMessageBox.Yes:
            return
        removed = self.store.clear_sync_data()
        self.reload_tracks()
        QMessageBox.information(
            self, "已清除",
            f"已清除 {removed} 条同步记录，所有列表归零。\n"
            "本地文件没有被删除；下次同步会自动重新关联。")

    # -- playback ---------------------------------------------------------

    def _play_index(self, index) -> None:
        row = self.model.row_at(index.row())
        if row is None:
            return
        if row["local_state"] == states.PENDING_REVIEW:
            from .approval_dialog import ApprovalDialog

            ApprovalDialog(self.store, int(row["song_id"]), self).exec()
            self.reload_tracks()
            return
        # Playing from a list replaces the queue with that list, starting here.
        self.queue = [int(item["song_id"]) for item in self.model.rows()]
        self.queue_pos = index.row()
        self._play_row(row)

    def _play_row(self, row) -> None:
        if not row["local_rel_path"]:
            QMessageBox.information(self, "还没有文件", "这首歌尚未下载。")
            return
        path = path_setting(self.config, "library") / row["local_rel_path"]
        if not path.exists():
            QMessageBox.warning(self, "文件不存在", f"找不到文件：\n{path}\n\n点「刷新」可重新核对。")
            return
        self.player.play_file(path, row["title"], f"{row['artist']} · {row['album']}")
        self._sync_queue_display()

    def _context_menu(self, position) -> None:
        index = self.view.indexAt(position)
        row = self.model.row_at(index.row()) if index.isValid() else None
        if row is None:
            return
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        play = menu.addAction("播放")
        download = menu.addAction("下载这首歌")
        open_folder = menu.addAction("打开所在文件夹")
        remove = None
        # 网易歌单 is a cloud view: deleting a row locally is meaningless because the
        # next sync puts it straight back.
        if self.list_key != states.LIST_ALL:
            menu.addSeparator()
            remove = menu.addAction("从列表中移除")

        has_file = bool(row["local_rel_path"])
        play.setEnabled(has_file)
        open_folder.setEnabled(has_file)
        already = row["local_state"] == states.DOWNLOADED
        download.setEnabled(not already and row["cloud_present"] == 1)
        download.setText("已下载" if already else "下载这首歌")

        chosen = menu.exec(self.view.viewport().mapToGlobal(position))
        if chosen is play:
            self._play_row(row)
        elif chosen is download:
            self._download_one(int(row["song_id"]))
        elif chosen is open_folder:
            self._open_folder(row)
        elif remove is not None and chosen is remove:
            self._remove_row(row)

    def _download_one(self, song_id: int) -> None:
        cookie = self._require_login()
        if not cookie:
            return
        self._start_download_ids([song_id])

    def _open_folder(self, row) -> None:
        from PySide6.QtGui import QDesktopServices

        path = path_setting(self.config, "library") / row["local_rel_path"]
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _remove_row(self, row) -> None:
        answer = QMessageBox.question(self, "从列表中移除",
                                      "只从数据库移除这条记录，本地文件保留。继续吗？")
        if answer != QMessageBox.Yes:
            return
        self.store.delete_tracks([int(row["song_id"])])
        self.reload_tracks()

    def _step(self, delta: int) -> None:
        if not self.queue:
            return
        self.queue_pos = (self.queue_pos + delta) % len(self.queue)
        row = self.store.get_track(self.queue[self.queue_pos])
        if row is not None:
            self._play_row(row)
        self._sync_queue_display()

    def open_now_playing(self) -> None:
        path = self.player.current_path
        if path is None or not path.exists():
            QMessageBox.information(self, "还没有在播放", "先双击一首已下载的歌。")
            return
        row = None
        for candidate in self.store.all_tracks():
            rel = candidate["local_rel_path"]
            if rel and (path_setting(self.config, "library") / rel) == path:
                row = candidate
                break
        self.now_page.show_track(path, row["title"] if row else path.stem,
                                 row["artist"] if row else "", row["album"] if row else "",
                                 self.player.media_player,
                                 row["cover_url"] if row else None)
        self.stack.setCurrentIndex(1)

    # -- play queue -------------------------------------------------------

    def toggle_queue(self) -> None:
        visible = not self.queue_panel.isVisible()
        self.queue_panel.setVisible(visible)
        if visible:
            self._sync_queue_display()

    def _sync_queue_display(self) -> None:
        self.queue_list.clear()
        for index, song_id in enumerate(self.queue):
            row = self.store.get_track(song_id)
            if row is None:
                continue
            prefix = "▶ " if index == self.queue_pos else "   "
            item = QListWidgetItem(f"{prefix}{row['title']} - {row['artist'] or ''}")
            item.setData(Qt.UserRole, index)
            self.queue_list.addItem(item)

    def _play_queue_item(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.UserRole)
        if isinstance(index, int) and 0 <= index < len(self.queue):
            self.queue_pos = index
            row = self.store.get_track(self.queue[index])
            if row is not None:
                self._play_row(row)
            self._sync_queue_display()

    def clear_queue(self) -> None:
        """Clearing the queue also stops playback — the bar must not lie about it."""
        self.queue_list.clear()
        self.queue = []
        self.queue_pos = -1
        self.player.stop()
        self.model.clear_progress()

    # -- sync -------------------------------------------------------------

    def start_sync(self) -> None:
        cookie = self._require_login()
        if not cookie:
            return
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("同步中…")
        self.status_label.setVisible(True)
        self.status_label.setText("正在同步歌单…")
        self._sync_worker = SyncWorker(self.db_path, cookie)
        self._sync_worker.done.connect(self._on_sync_done)
        self._sync_worker.failed.connect(self._on_worker_failed)
        self._sync_worker.start()

    def _on_sync_done(self, report) -> None:
        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("同步")
        self.status_label.setVisible(False)
        self._refresh_account_card()
        # The cloud list just changed; re-derive which files are already downloaded.
        # A reconcile failure must not swallow the result dialog again.
        try:
            reconcile_local(self.store, path_setting(self.config, "library"))
        except Exception as exc:
            logging.getLogger(__name__).warning("reconcile failed: %s", exc)
        self.reload_tracks()
        diff = report.diff_lines()
        body = report.as_line()
        if diff:
            body += "\n\n本次变化：\n" + "\n".join(diff)
            if report.added + report.removed > len(diff):
                body += "\n…"
        QMessageBox.information(self, "同步完成", body)

    def _on_worker_failed(self, message: str) -> None:
        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("同步")
        self.download_btn.setEnabled(True)
        self.download_btn.setText("下载")
        self.pause_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.status_label.setVisible(False)
        QMessageBox.critical(self, "操作失败", message)

    # -- download ---------------------------------------------------------

    def _update_download_label(self) -> None:
        if self._downloading:
            return
        count = len(self._selected_ids())
        self.download_btn.setText(f"下载选中的 {count} 首" if count else "下载")

    def _selected_ids(self) -> list[int]:
        return [int(self.model.row_at(index.row())["song_id"])
                for index in self.view.selectionModel().selectedRows()]

    def start_download(self) -> None:
        cookie = self._require_login()
        if not cookie:
            return
        selected = self._selected_ids()
        if selected:
            ids = selected
        else:
            ids = [int(row["song_id"]) for row in self.store.list_tracks(states.LIST_WAITING)]
        if not ids:
            QMessageBox.information(self, "没有可下载的歌",
                                    "先选中要下载的歌，或切到「等待下载」列表。")
            return
        self._start_download_ids(ids)

    def _start_download_ids(self, ids: list[int]) -> None:
        cookie = self._require_login()
        if not cookie:
            return
        self.download_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("暂停")
        self._downloading = True
        self.progress.setVisible(self.list_key == states.LIST_WAITING)
        self.progress.setRange(0, len(ids))
        self.progress.setValue(0)
        self.status_label.setVisible(True)
        self.status_label.setText(f"准备下载 {len(ids)} 首…")
        self._run_downloaded = 0
        self._run_review = 0
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)

        self._download_worker = DownloadWorker(self.db_path, ids, self.config, cookie)
        self._download_worker.track_started.connect(self._on_track_started)
        self._download_worker.track_finished.connect(self._on_track_finished)
        self._download_worker.progress.connect(self._on_progress)
        self._download_worker.track_progress.connect(self._on_track_progress)
        self._download_worker.failed.connect(self._on_worker_failed)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.start()

    def cancel_download(self) -> None:
        worker = self._download_worker
        if worker is None or not worker.isRunning():
            return
        worker.stop()
        self.cancel_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.status_label.setText("正在取消，清理临时文件…")

    def toggle_pause(self) -> None:
        worker = self._download_worker
        if worker is None or not worker.isRunning():
            return
        if self.pause_btn.text() == "暂停":
            worker.pause()
            self.pause_btn.setText("继续")
            self.status_label.setText("已暂停，当前正在下载的文件会继续传完")
        else:
            worker.resume()
            self.pause_btn.setText("暂停")

    def _on_track_started(self, song_id: int, title: str) -> None:
        self.status_label.setText(f"正在下载：{title}")

    def _on_track_finished(self, song_id: int, status: str, message: str) -> None:
        if status == "downloaded":
            self._run_downloaded += 1
        elif status == "review":
            self._run_review += 1
        self.reload_tracks()
        self.status_label.setText(f"{'已下载' if status == 'downloaded' else '转人工'}：{message}")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.setWindowTitle(f"NeteaseVault — 下载中 {done}/{total}")

    def _on_track_progress(self, song_id: int, fraction: float) -> None:
        self.model.set_progress(song_id, fraction)

    def _on_download_finished(self) -> None:
        self.download_btn.setEnabled(True)
        self.sync_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("暂停")
        self._downloading = False
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.progress.setVisible(False)
        self.status_label.setVisible(False)
        self.setWindowTitle(f"NeteaseVault {__version__}")
        self.model.clear_progress()
        self.reload_tracks()
        # Report this run, not the library total.
        QMessageBox.information(
            self, "下载结束",
            f"本次下载 {self._run_downloaded} 首，转人工 {self._run_review} 首。")
        self._run_downloaded = 0
        self._run_review = 0

    # -- misc -------------------------------------------------------------

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self.store, self)
        if dialog.exec():
            self.config = load_config()
            self.reload_tracks()

    def open_sources(self) -> None:
        from .source_manager import SourceManagerDialog

        SourceManagerDialog(self.store, self).exec()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._download_worker is not None and self._download_worker.isRunning():
            self._download_worker.stop()
            self._download_worker.wait(3000)
        self.now_page.stop()
        self.player.stop()
        self.store.close()
        super().closeEvent(event)
