"""Credential storage backed by Windows DPAPI.

The cookie never touches disk in plaintext and cannot be read by another Windows
account: protection is bound to the current user's logon credentials.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: _Blob) -> bytes:
    data = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return data


def protect(text: str) -> bytes:
    data_in = _to_blob(text.encode("utf-8"))
    data_out = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in), "NeteaseVault", None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out))
    if not ok:
        raise OSError("CryptProtectData 失败")
    return _from_blob(data_out)


def unprotect(blob: bytes) -> str:
    data_in = _to_blob(blob)
    data_out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out))
    if not ok:
        raise OSError("CryptUnprotectData 失败（凭证可能属于其他用户）")
    return _from_blob(data_out).decode("utf-8")


class CredentialStore:
    def __init__(self, path: Path):
        self.path = path

    def save_cookie(self, cookie: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(protect(cookie))

    def load_cookie(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            return unprotect(self.path.read_bytes())
        except OSError:
            return None

    def has_cookie(self) -> bool:
        return self.path.exists()

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
