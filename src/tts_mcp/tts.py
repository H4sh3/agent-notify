from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "tts_models/en/jenny/jenny"
_MODEL_LOCK = threading.Lock()

def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


_MODEL: Any | None = None
_MODEL_DEVICE: str | None = None
_MODEL_NAME: str | None = None


def _pick_device() -> str:
    try:
        import torch
    except ImportError:
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_model() -> Any:
    global _MODEL
    global _MODEL_DEVICE
    global _MODEL_NAME

    if _MODEL is not None:
        return _MODEL

    try:
        import torch
        from TTS.api import TTS
    except ImportError as exc:
        raise RuntimeError(
            "Missing Coqui TTS dependencies. Install project dependencies with "
            "`uv sync` before running the MCP server."
        ) from exc

    _MODEL_DEVICE = _pick_device()
    _MODEL_NAME = os.environ.get("TTS_MCP_MODEL", DEFAULT_MODEL)
    # Coqui reports download/model details on stdout. An MCP stdio server must
    # reserve stdout exclusively for JSON-RPC messages.
    with contextlib.redirect_stdout(sys.stderr):
        _MODEL = TTS(model_name=_MODEL_NAME, progress_bar=False).to(_MODEL_DEVICE)
    return _MODEL


def load_model() -> str:
    """Load or download the configured voice model and return its name."""
    _load_model()
    return _MODEL_NAME or DEFAULT_MODEL


def _default_speaker() -> str | None:
    configured = os.environ.get("TTS_MCP_SPEAKER")
    if configured is not None:
        return configured.strip() or None
    return None


def synthesize_text(
    text: str,
    output_path: Path,
    *,
    speaker_wav: Path | None = None,
    speaker: str | None = None,
) -> Path:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        raise ValueError("Text must not be empty.")

    with _MODEL_LOCK:
        model = _load_model()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {
            "text": normalized,
            "file_path": str(output_path),
        }
        if speaker_wav is not None:
            kwargs["speaker_wav"] = str(speaker_wav.expanduser().resolve())
        selected_speaker = speaker if speaker is not None else _default_speaker()
        if selected_speaker:
            kwargs["speaker"] = selected_speaker

        with contextlib.redirect_stdout(sys.stderr):
            model.tts_to_file(**kwargs)
    return output_path


def play_audio_file(
    audio_path: Path,
    *,
    stop_event: threading.Event | None = None,
) -> str:
    resolved = str(audio_path.expanduser().resolve())
    environment = os.environ.copy()
    if sys.platform == "linux" and not environment.get("XDG_RUNTIME_DIR"):
        runtime_dir = Path(f"/run/user/{os.getuid()}")
        if runtime_dir.is_dir():
            environment["XDG_RUNTIME_DIR"] = str(runtime_dir)

    if sys.platform == "linux":
        candidates = (
            ["paplay", resolved],
            ["aplay", "-q", resolved],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", resolved],
        )
    elif sys.platform == "darwin":
        candidates = (["afplay", resolved],)
    elif sys.platform == "win32":
        if stop_event is not None and stop_event.is_set():
            return "stopped"
        os.startfile(resolved)
        return "os.startfile"
    else:
        raise RuntimeError(f"Unsupported audio platform: {sys.platform}")

    failures: list[str] = []
    for command in candidates:
        if stop_event is not None and stop_event.is_set():
            return "stopped"
        try:
            process = subprocess.Popen(
                command,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
                text=True,
            )
        except FileNotFoundError:
            continue

        while True:
            if stop_event is not None and stop_event.is_set():
                process.terminate()
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                return "stopped"
            try:
                _, stderr = process.communicate(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                continue

        if process.returncode == 0:
            return command[0]
        detail = stderr.strip() or f"exit status {process.returncode}"
        failures.append(f"{command[0]}: {detail}")

    if failures:
        raise RuntimeError("Audio playback failed: " + "; ".join(failures))
    raise FileNotFoundError("No supported audio player was found.")
