from __future__ import annotations

from pathlib import Path

from tts_mcp.overlay import play_message
from tts_mcp.server import output_dir
from tts_mcp.tts import load_model, synthesize_text, text_hash

TEST_MESSAGE = "Agent Notify is installed and ready."


def prepare_and_test(audio_path: Path | None = None) -> str:
    destination = audio_path or output_dir() / f"setup-{text_hash(TEST_MESSAGE)}.wav"

    print("Loading the voice model. The first run may download several files...", flush=True)
    model_name = load_model()
    print(f"Voice model ready: {model_name}", flush=True)

    if not destination.exists() or destination.stat().st_size == 0:
        print("Synthesizing the test message...", flush=True)
        synthesize_text(TEST_MESSAGE, destination)
    else:
        print(f"Using cached test audio: {destination}", flush=True)

    print("Opening the test notification...", flush=True)
    player = play_message(TEST_MESSAGE, destination)
    if player == "tts-disabled":
        print("Test complete: the notification appeared with TTS disabled.")
    else:
        print(f"Test complete: audio played with {player}.")
    return player


def main() -> int:
    prepare_and_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
