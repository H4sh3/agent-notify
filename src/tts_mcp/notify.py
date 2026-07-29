from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tts_mcp.overlay import play_message
from tts_mcp.tts import synthesize_text, text_hash

DEFAULT_MESSAGE = "Codex finished the task."
MAX_MESSAGE_LENGTH = 280


def notification_message(raw_payload: str | None) -> str:
    if not raw_payload:
        return DEFAULT_MESSAGE
    try:
        payload: dict[str, Any] = json.loads(raw_payload)
    except (json.JSONDecodeError, TypeError):
        return DEFAULT_MESSAGE

    event_type = payload.get("type")
    if event_type and event_type != "agent-turn-complete":
        return ""

    candidate = (
        payload.get("last-assistant-message")
        or payload.get("last_assistant_message")
        or payload.get("message")
    )
    if not isinstance(candidate, str) or not candidate.strip():
        return DEFAULT_MESSAGE

    message = " ".join(candidate.split())
    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[: MAX_MESSAGE_LENGTH - 1].rstrip() + "…"
    return message


def _run_worker(message: str) -> int:
    output_dir = Path.home() / ".local" / "share" / "tts-mcp" / "audio"
    output_path = output_dir / f"notify-jenny-{text_hash(message)}.wav"
    if not output_path.exists() or output_path.stat().st_size == 0:
        synthesize_text(message, output_path)
    play_message(message, output_path)
    return 0


def _spawn_worker(message: str) -> int:
    subprocess.Popen(
        [sys.executable, "-m", "tts_mcp.notify", "--worker", message],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        return _run_worker(sys.argv[2])

    raw_payload = sys.argv[1] if len(sys.argv) >= 2 else None
    message = notification_message(raw_payload)
    return _spawn_worker(message) if message else 0


if __name__ == "__main__":
    raise SystemExit(main())
