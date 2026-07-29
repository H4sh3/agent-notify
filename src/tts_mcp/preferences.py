from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from tts_mcp.playback_queue import state_dir

SETTINGS_FILENAME = "settings.json"


def settings_path() -> Path:
    return state_dir() / SETTINGS_FILENAME


def _read_settings(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def tts_enabled(path: Path | None = None) -> bool:
    value = _read_settings(path or settings_path()).get("tts_enabled", True)
    return value if isinstance(value, bool) else True


def set_tts_enabled(enabled: bool, path: Path | None = None) -> Path:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    settings = _read_settings(target)
    settings["tts_enabled"] = enabled
    content = json.dumps(settings, indent=2, sort_keys=True) + "\n"

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.replace(temporary_name, target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return target
