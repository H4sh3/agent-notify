import io
import json

from tts_mcp.notify import DEFAULT_MESSAGE, notification_message
from tts_mcp.server import handle_speak, process_message, serve
from tts_mcp.tts import text_hash


def test_text_hash_is_stable():
    assert text_hash("hello") == text_hash("hello")
    assert len(text_hash("hello")) == 16


def test_process_message_initializes_with_instructions():
    response = process_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    assert response is not None
    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert "exactly two concise sentences" in response["result"]["instructions"]
    assert "final tool call" in response["result"]["instructions"]


def test_process_message_tools_list():
    response = process_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert response is not None
    assert response["result"]["tools"][0]["name"] == "speak"


def test_serve_uses_json_lines():
    input_stream = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}) + "\n"
    )
    output_stream = io.StringIO()
    serve(input_stream, output_stream)
    response = json.loads(output_stream.getvalue())
    assert response["id"] == 3
    assert response["result"]["tools"][0]["name"] == "speak"


def test_handle_speak_reuses_existing_audio(monkeypatch, tmp_path):
    audio_path = tmp_path / f"speak-{text_hash('done' + chr(0) + 'default')}.wav"
    audio_path.write_bytes(b"wave")
    monkeypatch.setattr("tts_mcp.server.output_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "tts_mcp.server.play_message",
        lambda message, path: "test-player",
    )

    result = handle_speak({"message": "done", "play_audio": True})
    assert result["audio_path"] == str(audio_path)
    assert result["played"] is True


def test_notification_payload_uses_last_assistant_message():
    payload = json.dumps(
        {
            "type": "agent-turn-complete",
            "last-assistant-message": "The task is complete.",
        }
    )
    assert notification_message(payload) == "The task is complete."
    assert notification_message(None) == DEFAULT_MESSAGE
