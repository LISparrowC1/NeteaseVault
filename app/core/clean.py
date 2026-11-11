"""Tag stripping and verification.

Two layers, both required:

1. container cleanup -- remove junk that does not belong to the audio stream at all
   (leading ID3v2 on FLAC, trailing ID3v1 / APEv2 / Lyrics3);
2. metadata rewrite -- keep exactly the whitelisted fields.

A file only reaches the library when re-parsing it proves both layers held.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_FLAC_BLOCKS = {0, 1, 4}          # STREAMINFO, PADDING, VORBIS_COMMENT
ALLOWED_ID3_FRAMES = {"TIT2", "TPE1", "TALB", "USLT"}
ALLOWED_FLAC_FIELDS = {"TITLE", "ARTIST", "ALBUM", "LYRICS"}

_TIME_LINE = re.compile(r"^\[\d{1,3}:\d{1,2}[.:]\d{1,3}\]")
_HEADER_LINE = re.compile(r"^\[(ar|ti|al|by|offset|re|ve|length):", re.IGNORECASE)


@dataclass
class CleanReport:
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def strip_lyric_header(text: str | None) -> str:
    """Keep only timed lines; drop [ar:]/[ti:]/[by:] style headers."""
    if not text:
        return ""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _HEADER_LINE.match(stripped):
            continue
        if _TIME_LINE.match(stripped):
            kept.append(stripped)
    return "\n".join(kept)


# -- container layer ------------------------------------------------------

def _syncsafe(raw: bytes) -> int:
    return ((raw[0] & 0x7F) << 21) | ((raw[1] & 0x7F) << 14) | ((raw[2] & 0x7F) << 7) | (raw[3] & 0x7F)


def strip_id3v2_prefix(data: bytes) -> tuple[bytes, int]:
    removed = 0
    while data[:3] == b"ID3" and len(data) >= 10:
        size = _syncsafe(data[6:10])
        footer = 10 if (data[5] & 0x10) else 0
        total = 10 + size + footer
        if total > len(data):
            break
        data = data[total:]
        removed += 1
    return data, removed


def strip_trailing_tags(data: bytes) -> tuple[bytes, list[str]]:
    removed: list[str] = []
    changed = True
    while changed:
        changed = False
        if len(data) > 128 and data[-128:-125] == b"TAG":
            data = data[:-128]
            removed.append("id3v1")
            changed = True
        if len(data) > 32 and data[-32:-24] == b"APETAGEX":
            size = int.from_bytes(data[-20:-16], "little")
            if 32 <= size <= len(data):
                data = data[:-size]
                removed.append("apev2")
                changed = True
        if len(data) > 15 and data[-9:-1] == b"LYRICS200":
            try:
                size = int(data[-15:-9])
            except ValueError:
                break
            if 0 < size <= len(data):
                data = data[:-size]
                removed.append("lyrics3")
                changed = True
    return data, removed


# -- metadata layer -------------------------------------------------------

def _write_flac_tags(path: Path, tags: dict[str, str]) -> None:
    from mutagen.flac import FLAC

    audio = FLAC(str(path))
    audio.clear_pictures()
    audio.delete()
    for key, value in tags.items():
        if value:
            audio[key] = [value]
    audio.save()


def _write_mp3_tags(path: Path, tags: dict[str, str]) -> None:
    from mutagen.id3 import ID3, TALB, TIT2, TPE1, USLT, ID3NoHeaderError

    try:
        audio = ID3(str(path))
        audio.delete()
    except ID3NoHeaderError:
        audio = ID3()
    if tags.get("TITLE"):
        audio.add(TIT2(encoding=3, text=[tags["TITLE"]]))
    if tags.get("ARTIST"):
        audio.add(TPE1(encoding=3, text=[tags["ARTIST"]]))
    if tags.get("ALBUM"):
        audio.add(TALB(encoding=3, text=[tags["ALBUM"]]))
    if tags.get("LYRICS"):
        audio.add(USLT(encoding=3, lang="chi", desc="", text=tags["LYRICS"]))
    audio.save(str(path), v2_version=3)


# -- verification ---------------------------------------------------------

def _parse_vorbis_comment(body: bytes) -> list[str]:
    """VORBIS_COMMENT is length-prefixed binary, not plain text."""
    fields: list[str] = []
    if len(body) < 8:
        return fields
    vendor_len = int.from_bytes(body[0:4], "little")
    offset = 4 + vendor_len
    if offset + 4 > len(body):
        return fields
    count = int.from_bytes(body[offset:offset + 4], "little")
    offset += 4
    for _ in range(count):
        if offset + 4 > len(body):
            break
        length = int.from_bytes(body[offset:offset + 4], "little")
        offset += 4
        if offset + length > len(body):
            break
        fields.append(body[offset:offset + length].decode("utf-8", errors="replace"))
        offset += length
    return fields


def _verify_flac(path: Path) -> tuple[dict, list[str]]:
    problems: list[str] = []
    data = path.read_bytes()
    if data[:3] == b"ID3":
        problems.append("文件头仍有 ID3v2 块")
        data, _ = strip_id3v2_prefix(data)
    if data[:4] != b"fLaC":
        problems.append("不是合法的 FLAC 流")
        return {"blocks": []}, problems

    blocks: list[int] = []
    fields: list[str] = []
    offset = 4
    while offset + 4 <= len(data):
        header = data[offset]
        is_last = header & 0x80
        block_type = header & 0x7F
        length = int.from_bytes(data[offset + 1:offset + 4], "big")
        body = data[offset + 4:offset + 4 + length]
        blocks.append(block_type)
        if block_type not in ALLOWED_FLAC_BLOCKS:
            problems.append(f"存在多余的元数据块 type={block_type}")
        if block_type == 4:
            for entry in _parse_vorbis_comment(body):
                key = entry.split("=", 1)[0].strip()
                fields.append(key)
                if key.upper() not in ALLOWED_FLAC_FIELDS:
                    problems.append(f"存在非白名单字段 {key}")
        if is_last:
            break
        offset += 4 + length

    if 0 not in blocks:
        problems.append("缺少 STREAMINFO")
    if data[-128:-125] == b"TAG":
        problems.append("文件尾仍有 ID3v1")
    if data[-32:-24] == b"APETAGEX":
        problems.append("文件尾仍有 APEv2")
    return {"blocks": blocks, "fields": fields}, problems


def _verify_mp3(path: Path) -> tuple[dict, list[str]]:
    problems: list[str] = []
    data = path.read_bytes()
    frames: list[str] = []
    if data[:3] != b"ID3":
        problems.append("缺少 ID3v2 头")
    else:
        size = _syncsafe(data[6:10])
        body = data[10:10 + size]
        offset = 0
        while offset + 10 <= len(body):
            frame_id = body[offset:offset + 4].decode("latin-1")
            if not frame_id.strip("\x00"):
                break
            frame_size = int.from_bytes(body[offset + 4:offset + 8], "big")
            frames.append(frame_id)
            if frame_id not in ALLOWED_ID3_FRAMES:
                problems.append(f"存在非白名单帧 {frame_id}")
            offset += 10 + frame_size
    if data[-128:-125] == b"TAG":
        problems.append("文件尾仍有 ID3v1")
    if data[-32:-24] == b"APETAGEX":
        problems.append("文件尾仍有 APEv2")
    return {"frames": frames}, problems


def strip_flac_extra_blocks(data: bytes) -> tuple[bytes, list[int]]:
    """Keep STREAMINFO only; drop SEEKTABLE, APPLICATION, PICTURE, ... .

    mutagen only manages the comment block, so anything else has to go before it
    touches the file.
    """
    if data[:4] != b"fLaC":
        return data, []
    blocks: list[int] = []
    kept: list[tuple[int, bytes]] = []
    offset = 4
    while offset + 4 <= len(data):
        header = data[offset]
        is_last = header & 0x80
        block_type = header & 0x7F
        length = int.from_bytes(data[offset + 1:offset + 4], "big")
        if offset + 4 + length > len(data):
            break
        blocks.append(block_type)
        if block_type == 0:
            kept.append((block_type, data[offset + 4:offset + 4 + length]))
        offset += 4 + length
        if is_last:
            break

    out = bytearray(data[:4])
    for index, (block_type, body) in enumerate(kept):
        last_flag = 0x80 if index == len(kept) - 1 else 0
        out.append(last_flag | block_type)
        out += len(body).to_bytes(3, "big")
        out += body
    out += data[offset:]
    return bytes(out), blocks


def clean_file(path: Path, tags: dict[str, str]) -> CleanReport:
    """Strip everything not whitelisted, then prove it by re-parsing."""
    report = CleanReport()
    ext = path.suffix.lower().lstrip(".")
    if ext not in {"flac", "mp3"}:
        report.problems.append(f"暂不支持的格式: {ext}")
        return report

    raw = path.read_bytes()
    report.before["bytes"] = len(raw)
    report.before["head"] = raw[:4].hex()

    stripped, id3_count = strip_id3v2_prefix(raw)
    if id3_count:
        report.before["id3v2_prefix"] = id3_count
    stripped, trailing = strip_trailing_tags(stripped)
    if trailing:
        report.before["trailing"] = trailing

    if ext == "flac":
        stripped, blocks = strip_flac_extra_blocks(stripped)
        if blocks:
            report.before["blocks"] = blocks

    path.write_bytes(stripped)

    if ext == "flac":
        if stripped[:4] != b"fLaC":
            report.problems.append("去壳后不是合法 FLAC")
            return report
        _write_flac_tags(path, tags)
        stats, problems = _verify_flac(path)
    else:
        _write_mp3_tags(path, tags)
        stats, problems = _verify_mp3(path)

    report.after.update(stats)
    report.after["bytes"] = path.stat().st_size
    report.problems.extend(problems)
    return report
