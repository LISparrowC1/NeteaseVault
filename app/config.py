"""Program root, config loading and defaults.

The program is meant to be a green, folder-local application: every mutable file
(config, database, logs, library) lives next to the executable. In development the
project folder plays that role.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "paths": {
        "library": "music",
        "staging": "data/staging",
        "usb_target": "",
    },
    "download": {
        # Order is user-editable from the settings page.
        "order": ["musicdl", "source", "official"],
        "concurrency": 2,
        "retries": 2,
    },
    "quality": {
        "floor_after_approval": "320k",
        # Below this the file cannot be lossless; 400..600 is the manual grey zone.
        "min_lossless_bitrate": 400,
        "manual_lossless_bitrate": 600,
    },
    "rate": {
        "search_interval_s": 1.5,
        "search_window_per_min": 20,
        "download_interval_s": 0.5,
        "download_window_per_min": 60,
    },
}


def app_root() -> Path:
    """Writable root: config, database, logs and the library live here."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundle_root() -> Path:
    """Read-only resources shipped with the program.

    Bundled data (engine, runtime, schema.sql) and user data both live in ``data``.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def engine_dir() -> Path:
    return bundle_root() / "engine"


def user_scripts_dir() -> Path:
    """Imported source scripts are runtime data, not bundled resources."""
    return data_dir() / "engine" / "scripts"


def data_dir() -> Path:
    """Everything the program writes at runtime, except the music library."""
    return app_root() / "data"


def temp_dir() -> Path:
    """Third-party temp files also stay inside the program folder."""
    return data_dir() / "tmp"


def logs_dir() -> Path:
    return data_dir() / "logs"


def ensure_layout() -> None:
    """Create only the two top-level folders a fresh copy needs.

    `music/` is the library; `data/` holds the database, credentials, logs, cache
    and staging area. Sub-folders are created on demand.
    """
    (app_root() / "music").mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
    temp_dir().mkdir(parents=True, exist_ok=True)
    if not config_path().exists():
        save_config(json.loads(json.dumps(DEFAULTS)))


def config_path() -> Path:
    return data_dir() / "config.json"


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return json.loads(json.dumps(DEFAULTS))
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULTS))
    return _merge(DEFAULTS, stored if isinstance(stored, dict) else {})


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def path_setting(config: dict[str, Any], key: str) -> Path:
    value = config["paths"][key]
    p = Path(value)
    return p if p.is_absolute() else app_root() / p
