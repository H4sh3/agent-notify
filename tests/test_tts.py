import subprocess
import threading
from pathlib import Path

import pytest

from tts_mcp.tts import play_audio_file


class FakeProcess:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.terminated = False
        self.killed = False

    def communicate(self, timeout=None):
        return "", self.stderr

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


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

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr("tts_mcp.tts.subprocess.Popen", fake_popen)

    assert play_audio_file(audio_path) == "paplay"
    assert calls[0][1]["env"]["XDG_RUNTIME_DIR"] == "/run/user/1234"
    assert calls[0][1]["start_new_session"] is True


def test_play_audio_falls_back_after_player_failure(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    audio_path.touch()
    results = iter(
        [
            FakeProcess(1, "connection refused"),
            FakeProcess(0),
        ]
    )

    monkeypatch.setattr("tts_mcp.tts.sys.platform", "linux")
    monkeypatch.setattr(
        "tts_mcp.tts.subprocess.Popen",
        lambda *args, **kwargs: next(results),
    )

    assert play_audio_file(audio_path) == "aplay"


def test_play_audio_reports_player_errors(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    audio_path.touch()

    monkeypatch.setattr("tts_mcp.tts.sys.platform", "darwin")
    monkeypatch.setattr(
        "tts_mcp.tts.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(2, "device busy"),
    )

    with pytest.raises(RuntimeError, match=r"afplay: device busy"):
        play_audio_file(audio_path)


def test_play_audio_stops_active_player(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    audio_path.touch()
    stop_event = threading.Event()

    class PlayingProcess(FakeProcess):
        def communicate(self, timeout=None):
            if not self.terminated:
                stop_event.set()
                raise subprocess.TimeoutExpired("paplay", timeout)
            return "", ""

    process = PlayingProcess()
    monkeypatch.setattr("tts_mcp.tts.sys.platform", "linux")
    monkeypatch.setattr(
        "tts_mcp.tts.subprocess.Popen",
        lambda *args, **kwargs: process,
    )

    assert play_audio_file(audio_path, stop_event=stop_event) == "stopped"
    assert process.terminated is True
    assert process.killed is False
