"""QR-code login against the netease web API.

State machine (verified against the live endpoint):

    800 二维码不存在或已过期
    801 等待扫码
    802 已扫码，等待手机确认
    803 授权成功（Set-Cookie 带 MUSIC_U）
    other 服务端拒绝，message 里带原因（例如 8821 风控）

The QR is rendered from an inline SVG (segno) so no image library is needed.
"""
from __future__ import annotations

import logging
import time

import requests
from PySide6.QtCore import QByteArray, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from ..security import CredentialStore
from . import theme

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BASE = "https://music.163.com"
log = logging.getLogger("neteasevault.qr")


class QrLoginDialog(QDialog):
    def __init__(self, credentials: CredentialStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扫码登录")
        self.resize(380, 520)
        self.credentials = credentials
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Referer": f"{BASE}/",
            "Origin": BASE,
            "Accept": "*/*",
        })
        self.unikey: str | None = None
        self.deadline = 0.0
        self.unknown_streak = 0

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)

        self.qr_label = QLabel("正在获取二维码…")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setMinimumSize(280, 280)
        layout.addWidget(self.qr_label)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{theme.TEXT_DIM};")
        layout.addWidget(self.status)

        self.hint = QLabel("扫码遇到问题？可以先点「重新获取二维码」；"
                           "仍失败可在账户设置里改用 Cookie 登录。")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:{theme.TEXT_FAINT}; font-size:11px;")
        layout.addWidget(self.hint)

        refresh = QPushButton("重新获取二维码")
        refresh.clicked.connect(self.start)
        layout.addWidget(refresh)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.start()

    # -- flow -------------------------------------------------------------

    def start(self) -> None:
        self.timer.stop()
        self.unknown_streak = 0
        self.status.setText("正在获取二维码…")
        try:
            # Warm the session first; some deployments bind the unikey to it.
            self.session.get(f"{BASE}/login", timeout=15)
            response = self.session.get(f"{BASE}/api/login/qrcode/unikey",
                                        params={"type": 1}, timeout=15).json()
        except Exception as exc:
            log.warning("unikey request failed: %s", exc)
            self.status.setText(f"获取二维码失败：{exc}")
            return
        if response.get("code") != 200 or not response.get("unikey"):
            log.warning("unikey rejected: %s", response)
            self.status.setText("获取二维码失败，请稍后重试")
            return
        self.unikey = response["unikey"]
        self.deadline = time.time() + 180
        self._render(f"{BASE}/login?codekey={self.unikey}")
        self.status.setText("请用网易云音乐 App 扫码")
        self.timer.start(2000)

    def _render(self, payload: str) -> None:
        import segno

        qr = segno.make(payload, error="m")
        svg = qr.svg_inline(scale=8, border=2, dark="#000000", light="#ffffff")
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pixmap = QPixmap(260, 260)
        pixmap.fill(Qt.white)
        from PySide6.QtGui import QPainter

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        self.qr_label.setPixmap(pixmap)

    def _poll(self) -> None:
        if not self.unikey:
            self.timer.stop()
            return
        if time.time() > self.deadline:
            self.timer.stop()
            self.status.setText("二维码已过期，请重新获取")
            return
        try:
            response = self.session.get(f"{BASE}/api/login/qrcode/client/login",
                                        params={"key": self.unikey, "type": 1}, timeout=15)
            data = response.json()
        except Exception as exc:
            log.warning("qr poll failed: %s", exc)
            return

        code = data.get("code")
        message = str(data.get("message") or "")

        if code == 801:
            self.status.setText("等待扫码…")
        elif code == 802:
            self.status.setText("已扫码，请在手机上点「确认登录」")
        elif code == 803:
            self.status.setText("登录成功")
            self.timer.stop()
            self._finish(response, data)
        elif code == 800:
            self.timer.stop()
            self.status.setText("二维码已过期或不存在，请重新获取")
        elif code == 8821:
            # NetEase closed this login method for third-party clients; the message
            # is explicit ("请切换其他登录方式或升级新版本再试"). Retrying is useless.
            log.warning("qr login disabled by server: %s", message)
            self.timer.stop()
            self.status.setText(
                "网易已关闭扫码登录\n"
                f"服务端返回：{message or '8821'}\n"
                "请改用 Cookie 登录（账户 → 打开登录页）。")
            self.qr_label.clear()
            self.qr_label.setText("扫码登录不可用")
        else:
            # Unknown refusal: keep the server text and give it a few chances.
            log.warning("qr poll returned code=%s message=%s", code, message)
            self.unknown_streak += 1
            detail = f"（{message}）" if message else ""
            if self.unknown_streak >= 3:
                self.timer.stop()
                self.status.setText(f"登录服务返回 {code}{detail}\n请改用 Cookie 登录。")
            else:
                self.status.setText(f"登录服务返回 {code}{detail}，正在重试…")

    def _finish(self, response, data: dict) -> None:
        jar: dict[str, str] = {}
        for cookie in self.session.cookies:
            jar[cookie.name] = cookie.value
        for cookie in getattr(response, "cookies", []) or []:
            jar[cookie.name] = cookie.value
        if "MUSIC_U" not in jar:
            text = str(data.get("cookie") or "")
            if "MUSIC_U" in text:
                self.credentials.save_cookie(text)
                self.accept()
                return
        if "MUSIC_U" not in jar:
            log.warning("803 without MUSIC_U: %s", data)
            self.status.setText("手机已确认，但服务端没有下发凭证。\n请重新获取二维码，或改用 Cookie 登录。")
            return
        self.credentials.save_cookie("; ".join(f"{k}={v}" for k, v in jar.items()))
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        super().closeEvent(event)
