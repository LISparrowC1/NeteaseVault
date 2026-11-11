"""Mirror the library onto a USB drive and emit a relative-path playlist.

The library keeps its layout, so the same relative paths work on the target. A
manifest avoids re-hashing every file: hashes are computed once when a file is first
copied and reused until its size or mtime changes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_REL = Path(".nv") / "manifest.json"


@dataclass
class UsbReport:
    copied: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)
    bytes_copied: int = 0

    def as_line(self) -> str:
        return (f"U 盘同步完成：复制 {self.copied} 个，跳过 {self.skipped} 个，"
                f"{self.bytes_copied / 1048576:.1f} MB"
                + (f"，失败 {len(self.failed)} 个" if self.failed else ""))


def _md5(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest(target: Path) -> dict:
    path = target / MANIFEST_REL
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_manifest(target: Path, manifest: dict) -> None:
    path = target / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


def sync_to_usb(library: Path, target: Path) -> UsbReport:
    report = UsbReport()
    if not library.exists():
        raise FileNotFoundError(f"库目录不存在: {library}")
    target.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(target)

    for source in library.rglob("*"):
        if not source.is_file():
            continue
        rel = source.relative_to(library).as_posix()
        stat = source.stat()
        entry = manifest.get(rel)
        destination = target / rel

        if (destination.exists() and entry
                and entry.get("size") == stat.st_size
                and abs(entry.get("mtime", 0) - stat.st_mtime) < 1):
            report.skipped += 1
            continue

        # Hashes are only recomputed when the cached entry cannot be trusted.
        digest = entry.get("md5") if entry and entry.get("size") == stat.st_size else None
        if digest is None:
            digest = _md5(source)

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            report.failed.append(f"{rel}: {exc}")
            continue
        report.copied += 1
        report.bytes_copied += stat.st_size
        manifest[rel] = {"size": stat.st_size, "mtime": stat.st_mtime, "md5": digest}

    _save_manifest(target, manifest)
    return report


def write_playlist(library: Path, destination: Path, rows, name: str = "我喜欢的音乐") -> int:
    """Write a UTF-8 .m3u8 with paths relative to the library root."""
    lines = ["#EXTM3U"]
    count = 0
    for row in rows:
        rel = row["local_rel_path"]
        if not rel:
            continue
        if not (library / rel).exists():
            continue
        seconds = int((row["duration_ms"] or 0) / 1000)
        lines.append(f"#EXTINF:{seconds},{row['artist']} - {row['title']}")
        lines.append(rel.replace("\\", "/"))
        count += 1
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count
