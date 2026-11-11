"""Small QThread wrapper so long network work never freezes the window."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, func: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:  # noqa: D401
        try:
            result = self._func(*self._args, **self._kwargs)
        except Exception as exc:  # surface the message, keep the traceback in stderr
            traceback.print_exc()
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)
