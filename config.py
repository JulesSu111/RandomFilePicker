"""Persistent application settings."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_EXTENSIONS = [
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif",
    ".tiff", ".svg", ".avif",
]

DEFAULT_CONFIG = {
    "root": "", "selected_extensions": DEFAULT_EXTENSIONS, "custom_extensions": [],
    "mode": "recent", "recent_n": 50, "open_behavior": "both", "excluded_folders": [],
    "excluded_files": [], "filename_filters": [], "history": [], "recent_picker_memory": [], "language": "zh_CN",
    "scope_enabled": {}, "geometry": "",
}


def config_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "RandomFilePicker" / "config.json"


def load_config() -> dict:
    defaults = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                for k, v in DEFAULT_CONFIG.items()}
    path = config_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("configuration is not an object")
        for key in defaults:
            if key in data and isinstance(data[key], type(defaults[key])):
                defaults[key] = data[key]
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return defaults


def save_config(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temporary.replace(path)
