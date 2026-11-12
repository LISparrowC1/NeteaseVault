"""Login dialog: paste a cookie, validate it, or wipe stored credentials."""
from __future__ import annotations

import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from ..core.netease import NeteaseClient
from ..security import CredentialStore
from .messagebox import QMessageBox

COOKIE_PAIR = re.compile(r"([A-Za-z0-9_]+)=([^;\"'\s]+)")
JSON_PAIR = re.compile(r'"([A-Za-z0-9_]+)"\s*:\s*"([^"]+)"')
KEEP = ("MUSIC_U", "__csrf", "MUSIC_A", "NMTID", "__remember_me")


def normalize_cookie(text: str) -> str:
    """Accept a raw header, a DevTools copy, JSON, or a bare pair list."""
    pairs = COOKIE_PAIR.findall(text or "") or JSON_PAIR.findall(text or "")
    if not pairs:
        return ""
    picked: dict[str, str] = {}
    for name, value in pairs:
        if name in KEEP and value:
            picked[name] = value
    if "MUSIC_U" not in picked:
        return ""
    return "; ".join(f"{name}={value}" for name, value in picked.items())


class LoginDialog(QDialog):
    def __init__(self, credentials: CredentialStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("网易云登录")
        self.resize(600, 420)
        self.credentials = credentials

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        tip = QLabel(
            "1) 点「打开登录页」，在浏览器里登录 music.163.com\n"
            "2) 按 F12 → Application → Cookies → music.163.com，找到 MUSIC_U\n"
            "3) 整段复制（或直接复制请求头里的 Cookie）粘贴到下面\n"
            "扫码登录已被网易关闭（服务端返回 8821），目前 Cookie 是唯一可用方式。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8A8F98;")
        layout.addWidget(tip)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("MUSIC_U=...; __csrf=...;   （粘贴整段也行，会自动提取）")
        layout.addWidget(self.editor, 1)

        row = QHBoxLayout()
        self.open_btn = QPushButton("打开登录页")
        self.open_btn.setObjectName("Accent")
        self.open_btn.clicked.connect(self._open_page)
        self.paste_btn = QPushButton("从剪贴板粘贴")
        self.paste_btn.clicked.connect(self._paste)
        self.check_btn = QPushButton("检查登录状态")
        self.check_btn.clicked.connect(self._check)
        self.clear_btn = QPushButton("清除已保存的登录数据")
        self.clear_btn.clicked.connect(self._clear)
        for button in (self.open_btn, self.paste_btn, self.check_btn, self.clear_btn):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if credentials.load_cookie():
            self.editor.setPlaceholderText("已保存凭证（不显示明文）。要更换请粘贴新的 Cookie。")

    # -- helpers ----------------------------------------------------------

    def _current_cookie(self) -> str:
        text = self.editor.toPlainText().strip()
        return normalize_cookie(text) or (self.credentials.load_cookie() or "")

    def _open_page(self) -> None:
        QDesktopServices.openUrl(QUrl("https://music.163.com"))

    def _paste(self) -> None:
        text = QApplication.clipboard().text()
        if not text.strip():
            QMessageBox.information(self, "剪贴板为空", "先把 Cookie 复制到剪贴板。")
            return
        cookie = normalize_cookie(text)
        self.editor.setPlainText(cookie or text)
        if not cookie:
            QMessageBox.warning(self, "没找到 MUSIC_U",
                                "剪贴板内容里没有 MUSIC_U，请确认复制的是完整 Cookie。")

    def _check(self) -> None:
        cookie = self._current_cookie()
        if not cookie:
            QMessageBox.warning(self, "没有凭证", "请先粘贴 Cookie。")
            return
        try:
            profile = NeteaseClient(cookie).account()
        except Exception as exc:
            QMessageBox.critical(self, "检查失败", str(exc))
            return
        QMessageBox.information(
            self, "登录有效",
            f"已登录：{profile.get('nickname') or '（无昵称）'}\nUID：{profile['userId']}")

    def _clear(self) -> None:
        self.credentials.clear()
        self.editor.clear()
        QMessageBox.information(self, "已清除", "本地保存的登录数据已删除。")

    def _save(self) -> None:
        cookie = normalize_cookie(self.editor.toPlainText())
        if not cookie:
            QMessageBox.warning(
                self, "没有可用的凭证",
                "没有从粘贴内容里找到 MUSIC_U。\n"
                "请确认复制的是 music.163.com 的完整 Cookie。")
            return
        try:
            profile = NeteaseClient(cookie).account()
        except Exception as exc:
            QMessageBox.critical(self, "Cookie 无效", str(exc))
            return
        self.credentials.save_cookie(cookie)
        QMessageBox.information(
            self, "登录成功",
            f"已登录：{profile.get('nickname') or '（无昵称）'}\nUID：{profile['userId']}")
        self.accept()
