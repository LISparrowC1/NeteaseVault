"""Account page: who is logged in, health check, re-login, wipe credentials."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from ..core.netease import NeteaseClient
from ..db.store import Store
from ..security import CredentialStore
from . import theme
from .login_dialog import LoginDialog
from .messagebox import QMessageBox


class AccountDialog(QDialog):
    def __init__(self, credentials: CredentialStore, store: Store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("账户")
        self.resize(460, 300)
        self.credentials = credentials
        self.store = store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        self.title = QLabel("账户信息")
        self.title.setStyleSheet(f"font-size:16px; font-weight:700; color:{theme.TEXT};")
        layout.addWidget(self.title)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setStyleSheet(f"color:{theme.TEXT_DIM};")
        layout.addWidget(self.info)

        layout.addStretch(1)

        row = QHBoxLayout()
        self.check_btn = QPushButton("检查登录状态")
        self.check_btn.setObjectName("Accent")
        self.check_btn.clicked.connect(self._check)
        self.relogin_btn = QPushButton("重新登录")
        self.relogin_btn.clicked.connect(self._relogin)
        self.clear_btn = QPushButton("清除登录信息")
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.check_btn)
        row.addWidget(self.relogin_btn)
        row.addWidget(self.clear_btn)
        layout.addLayout(row)

        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignRight)

        self._refresh_label()

    def _refresh_label(self) -> None:
        nickname = self.store.get_meta("account_nickname") or ""
        uid = self.store.get_meta("account_uid") or ""
        if not self.credentials.has_cookie():
            self.info.setText("当前未登录。\n登录后才能同步「我喜欢的音乐」。")
            return
        if nickname:
            self.info.setText(f"已登录：{nickname}" + (f"（UID {uid}）" if uid else "")
                              + "\n凭证已用 Windows DPAPI 加密保存在本机。")
        else:
            self.info.setText("已保存凭证，但还没有同步过账户信息。\n点「检查登录状态」即可读取。")

    def _check(self, silent: bool = False) -> None:
        cookie = self.credentials.load_cookie()
        if not cookie:
            if not silent:
                QMessageBox.information(self, "未登录", "本地没有凭证，请先登录。")
            return
        try:
            profile = NeteaseClient(cookie).account()
        except Exception as exc:
            if not silent:
                QMessageBox.critical(self, "检查失败", str(exc))
            return
        self.store.set_meta("account_uid", str(profile["userId"]))
        self.store.set_meta("account_nickname", str(profile.get("nickname") or ""))
        self._refresh_label()
        if not silent:
            QMessageBox.information(
                self, "登录有效",
                f"昵称：{profile.get('nickname')}\nUID：{profile['userId']}")

    def _relogin(self) -> None:
        dialog = LoginDialog(self.credentials, self)
        if dialog.exec():
            self._check(silent=True)

    def _clear(self) -> None:
        self.credentials.clear()
        self.store.clear_meta("account_nickname")
        self.store.clear_meta("account_uid")
        self._refresh_label()
        QMessageBox.information(self, "已清除", "本地登录信息已删除。")
