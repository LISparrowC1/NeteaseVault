"""GUI entry point."""
from __future__ import annotations

import faulthandler
import logging
import os
import sys
import tempfile
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .config import app_root, data_dir, ensure_layout, temp_dir
from .ui import theme
from .ui.main_window import MainWindow


def _setup_logging() -> None:
    logs = app_root() / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    # A windowed build has nowhere to print, so keep hard crashes on disk.
    crash = open(logs / "crash.log", "a", encoding="utf-8")
    faulthandler.enable(file=crash)
    original_hook = sys.excepthook

    def _hook(exc_type, exc, tb):
        import traceback
        crash.write("".join(traceback.format_exception(exc_type, exc, tb)))
        crash.flush()
        original_hook(exc_type, exc, tb)

    sys.excepthook = _hook
    handler = TimedRotatingFileHandler(
        logs / "app.log", when="midnight", backupCount=30, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _prepare_ca_bundle() -> Path | None:
    """Keep a writable CA copy inside ``data/``.

    certifi ships inside the bundled ``data`` tree; pointing requests at a persistent
    copy means a moved installation and any future cleanup cannot break HTTPS.
    """
    try:
        import certifi
    except Exception:
        return None
    source = Path(certifi.where())
    if not source.is_file():
        return None
    target = app_root() / "data" / "cacert.pem"
    try:
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(source, target)
    except OSError:
        return None
    os.environ["REQUESTS_CA_BUNDLE"] = str(target)
    os.environ["SSL_CERT_FILE"] = str(target)
    return target


def _selftest() -> int:
    """Prove the frozen bundle can import and initialise without opening a window.

    A windowed exe has no stdout, so the result goes to a file next to it.
    """
    status, detail = "ok", ""
    try:
        # Keep even the selftest's temporary database inside the program folder.
        scratch = app_root() / "data" / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(scratch)
        tempfile.tempdir = str(scratch)
        from .core import clean, download, match, sync  # noqa: F401
        from .core.channels import musicdl_channel, official_channel, source_channel  # noqa: F401
        from .db.store import Store
        from .security import CredentialStore  # noqa: F401
        from .ui import main_window, source_manager  # noqa: F401

        # requests needs certifi's data file; a missing copy breaks every HTTPS call.
        import certifi
        if not Path(certifi.where()).is_file():
            raise RuntimeError('certifi CA bundle 缺失')

        # zhconv ships a data file; a missing copy breaks matching at runtime.
        from .core.normalize import normalize
        if normalize('陳奕迅') != '陈奕迅':
            raise RuntimeError('zhconv 字典不可用')

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "selftest.db")
            store.list_tracks()
            store.close()
    except Exception as exc:  # pragma: no cover - only during a broken build
        status, detail = "failed", f"{type(exc).__name__}: {exc}"
    Path(app_root() / "selftest.txt").write_text(f"selftest {status}\n{detail}\n", encoding="utf-8")
    return 0 if status == "ok" else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()

    ensure_layout()
    os.chdir(data_dir())
    tmp = temp_dir()
    os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(tmp)
    tempfile.tempdir = str(tmp)
    _prepare_ca_bundle()
    _setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("NeteaseVault")
    app.setStyleSheet(theme.STYLESHEET)
    window = MainWindow()
    screen = window.screen() or app.primaryScreen()
    available = screen.availableGeometry() if screen is not None else None
    if available is not None and available.isValid():
        # showMaximized can exceed the screen at 150% DPI and push the player bar
        # below the desktop; leave room for the window frame and show normally.
        window.setGeometry(available.adjusted(0, 0, -16, -16))
        window.show()
    else:
        window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
