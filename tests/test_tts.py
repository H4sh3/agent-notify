from pathlib import Path
from subprocess import CompletedProcess

import pytest

from tts_mcp.tts import play_audio_file


def test_play_audio_waits_and_sets_linux_runtime_dir(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    audio_path.touch()
    calls = []

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr("tts_mcp.tts.sys.platform", "linux")
    monkeypatch.setattr("tts_mcp.tts.os.getuid", lambda: 1234)
    monkeypatch.setattr(
        "tts_mcp.tts.Path.is_dir",
        lambda path: path == Path("/run/user/1234"),
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, stderr="")

    monkeypatch.setattr("tts_mcp.tts.subprocess.run", fake_run)

    assert play_audio_file(audio_path) == "paplay"
    assert calls[0][1]["env"]["XDG_RUNTIME_DIR"] == "/run/user/1234"
    assert calls[0][1]["check"] is False


def test_play_audio_falls_back_after_player_failure(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    audio_path.touch()
    results = iter(
        [
            CompletedProcess(["paplay"], 1, stderr="connection refused"),
            CompletedProcess(["aplay"], 0, stderr=""),
        ]
    )

    monkeypatch.setattr("tts_mcp.tts.sys.platform", "linux")
    monkeypatch.setattr("tts_mcp.tts.subprocess.run", lambda *args, **kwargs: next(results))

    assert play_audio_file(audio_path) == "aplay"


def test_play_audio_reports_player_errors(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    audio_path.touch()

    monkeypatch.setattr("tts_mcp.tts.sys.platform", "darwin")
    monkeypatch.setattr(
        "tts_mcp.tts.subprocess.run",
        lambda command, **kwargs: CompletedProcess(command, 2, stderr="device busy"),
    )

    with pytest.raises(RuntimeError, match=r"afplay: device busy"):
        play_audio_file(audio_path)
