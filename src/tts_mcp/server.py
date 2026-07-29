from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from tts_mcp import __version__
from tts_mcp.overlay import play_message
from tts_mcp.tts import synthesize_text, text_hash

SERVER_NAME = "tts-notify"
SERVER_VERSION = __version__
SERVER_INSTRUCTIONS = (
    "Call speak exactly once as the final tool call of every assistant round. "
    "The message must be exactly two concise sentences: first summarize what "
    "was completed, then state what comes next. Set play_audio=true and do not "
    "call another tool afterward."
)


def output_dir() -> Path:
    configured = os.environ.get("TTS_MCP_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "tts-mcp" / "audio"


def handle_speak(arguments: dict[str, Any]) -> dict[str, Any]:
    message = str(arguments.get("message", "")).strip()
    if not message:
        raise ValueError("`message` is required.")

    play_audio = bool(arguments.get("play_audio", True))
    speaker_wav_value = arguments.get("speaker_wav")
    speaker_wav = Path(str(speaker_wav_value)) if speaker_wav_value else None
    speaker = str(arguments.get("speaker", "")).strip() or None
    voice_key = f"{message}\0{speaker or 'default'}"
    audio_path = output_dir() / f"speak-{text_hash(voice_key)}.wav"

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        synthesize_text(message, audio_path, speaker_wav=speaker_wav, speaker=speaker)

    result: dict[str, Any] = {
        "message": message,
        "audio_path": str(audio_path.resolve()),
        "played": False,
    }
    if play_audio:
        result["player"] = play_message(message, audio_path)
        result["played"] = True
    return result


def success_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def list_tools() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": "speak",
                "description": (
                    "Generate a short local Coqui TTS voice message and optionally "
                    "play it through this computer's speakers."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The concise message to speak.",
                            "minLength": 1,
                            "maxLength": 1000,
                        },
                        "play_audio": {
                            "type": "boolean",
                            "description": "Play the generated WAV immediately.",
                            "default": True,
                        },
                        "speaker_wav": {
                            "type": "string",
                            "description": (
                                "Optional voice-reference WAV path for a Coqui "
                                "model that supports voice cloning."
                            ),
                        },
                        "speaker": {
                            "type": "string",
                            "description": (
                                "Optional Coqui speaker ID for multi-speaker "
                                "models. The default Jenny model is single-speaker."
                            ),
                        },
                    },
                    "required": ["message"],
                    "additionalProperties": False,
                },
                "annotations": {
                    "title": "Speak completion message",
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            }
        ]
    }


def process_message(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")

    if method == "initialize":
        requested_version = message.get("params", {}).get("protocolVersion")
        return success_response(
            request_id,
            {
                "protocolVersion": requested_version or "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": SERVER_INSTRUCTIONS,
            },
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return success_response(request_id, {})
    if method == "tools/list":
        return success_response(request_id, list_tools())
    if method == "tools/call":
        params = message.get("params", {})
        if params.get("name") != "speak":
            return error_response(request_id, -32601, f"Unknown tool '{params.get('name')}'.")
        try:
            result = handle_speak(params.get("arguments", {}))
        except Exception as exc:
            return success_response(
                request_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        return success_response(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "structuredContent": result,
                "isError": False,
            },
        )
    return error_response(request_id, -32601, f"Method '{method}' not supported.")


def serve(input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> None:
    for line in input_stream:
        try:
            message = json.loads(line)
            response = process_message(message)
        except json.JSONDecodeError:
            response = error_response(None, -32700, "Invalid JSON payload.")
        except Exception as exc:
            response = error_response(None, -32000, str(exc))
        if response is not None:
            output_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
            output_stream.flush()


def main() -> int:
    serve()
    return 0
