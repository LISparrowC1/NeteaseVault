"""Thin client for the Node engine (line-delimited JSON over stdio)."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

from ..config import user_scripts_dir as _user_scripts_dir
from typing import Any


class EngineError(RuntimeError):
    pass


class EngineClient:
    def __init__(self, engine_dir: Path, node_exe: str | None = None,
                 user_scripts_dir: Path | None = None):
        self.engine_dir = engine_dir
        self.user_scripts_dir = user_scripts_dir or _user_scripts_dir()
        self._node = node_exe
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._stderr_lines: list[str] = []

    # -- process ----------------------------------------------------------

    def _node_path(self) -> str:
        if self._node:
            return self._node
        runtime = self.engine_dir.parent / "runtime" / "node.exe"
        if runtime.exists():
            return str(runtime)
        found = shutil.which("node")
        if not found:
            raise EngineError("找不到 node 运行时")
        return found

    def _ensure(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        script = self.engine_dir / "index.js"
        if not script.exists():
            raise EngineError(f"缺少引擎入口: {script}")
        self.user_scripts_dir.mkdir(parents=True, exist_ok=True)
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):  # keep a console window from popping up
            creationflags = subprocess.CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            [self._node_path(), "--use-system-ca", str(script),
             "--user-scripts", str(self.user_scripts_dir)],
            cwd=str(self.engine_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creationflags,
        )
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        return self._proc

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr_lines.append(line.rstrip())
            del self._stderr_lines[:-200]

    # -- rpc --------------------------------------------------------------

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0) -> Any:
        with self._lock:
            proc = self._ensure()
            message_id = self._next_id
            self._next_id += 1
            payload = json.dumps({"id": message_id, "method": method, "params": params or {}},
                                 ensure_ascii=False)
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(payload + "\n")
            proc.stdin.flush()

            timer = threading.Timer(timeout, lambda: proc.kill())
            timer.start()
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        raise EngineError("引擎进程意外退出: " + self.last_stderr())
                    try:
                        reply = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if reply.get("id") != message_id:
                        continue
                    if not reply.get("ok"):
                        raise EngineError(reply.get("error") or "未知引擎错误")
                    return reply.get("result")
            finally:
                timer.cancel()

    def last_stderr(self, limit: int = 5) -> str:
        return " | ".join(self._stderr_lines[-limit:])

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        self._proc = None
