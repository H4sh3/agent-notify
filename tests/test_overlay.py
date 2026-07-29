import os
from pathlib import Path

import pytest

from tts_mcp import overlay


def test_play_message_can_disable_overlay(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    calls: list[Path] = []
    monkeypatch.setenv("TTS_MCP_OVERLAY", "off")
    monkeypatch.setattr(overlay, "tts_enabled", lambda: True)

    result = overlay.play_message(
        "Finished.",
        audio_path,
        playback=lambda path: calls.append(path) or "test-player",
    )

    assert result == "test-player"
    assert calls == [audio_path]


def test_audio_only_mode_honors_persisted_tts_setting(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    calls: list[Path] = []
    monkeypatch.setenv("TTS_MCP_OVERLAY", "off")
    monkeypatch.setattr(overlay, "tts_enabled", lambda: False)

    result = overlay.play_message(
        "Finished.",
        audio_path,
        playback=lambda path: calls.append(path) or "test-player",
    )

    assert result == "tts-disabled"
    assert calls == []


def test_play_message_falls_back_when_display_is_unavailable(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    calls: list[Path] = []
    monkeypatch.delenv("TTS_MCP_OVERLAY", raising=False)
    monkeypatch.setattr(overlay, "tts_enabled", lambda: True)
    monkeypatch.setattr(
        overlay,
        "_play_with_tk",
        lambda *args: (_ for _ in ()).throw(overlay._OverlayUnavailable()),
    )

    result = overlay.play_message(
        "Finished.",
        audio_path,
        playback=lambda path: calls.append(path) or "test-player",
    )

    assert result == "test-player"
    assert calls == [audio_path]


def test_unavailable_display_honors_persisted_tts_setting(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    calls: list[Path] = []
    monkeypatch.setattr(overlay, "tts_enabled", lambda: False)
    monkeypatch.setattr(
        overlay,
        "_play_with_tk",
        lambda *args: (_ for _ in ()).throw(overlay._OverlayUnavailable()),
    )

    result = overlay.play_message(
        "Finished.",
        audio_path,
        playback=lambda path: calls.append(path) or "test-player",
    )

    assert result == "tts-disabled"
    assert calls == []


def test_playback_errors_are_not_retried(monkeypatch, tmp_path):
    audio_path = tmp_path / "message.wav"
    monkeypatch.setattr(
        overlay,
        "_play_with_tk",
        lambda *args: (_ for _ in ()).throw(RuntimeError("device busy")),
    )

    with pytest.raises(RuntimeError, match="device busy"):
        overlay.play_message("Finished.", audio_path, playback=lambda _: "unused")


def test_find_x11_display_uses_available_socket(monkeypatch, tmp_path):
    display_socket = tmp_path / "X7"
    display_socket.touch()
    monkeypatch.setattr(Path, "is_socket", lambda path: path == display_socket)

    assert overlay._find_x11_display(tmp_path) == ":7"


def test_prepare_graphical_environment_recovers_codex_session(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    authority = runtime_dir / "gdm" / "Xauthority"
    authority.parent.mkdir(parents=True)
    authority.touch()
    (runtime_dir / "bus").touch()

    for name in (
        "DISPLAY",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(overlay.sys, "platform", "linux")
    monkeypatch.setattr(overlay.os, "getuid", lambda: 1234)
    monkeypatch.setattr(
        overlay,
        "Path",
        lambda value: runtime_dir if value == "/run/user/1234" else Path(value),
    )
    monkeypatch.setattr(overlay, "_find_x11_display", lambda: ":7")

    overlay._prepare_graphical_environment()

    assert os.environ["DISPLAY"] == ":7"
    assert os.environ["XAUTHORITY"] == str(authority)
    assert os.environ["XDG_RUNTIME_DIR"] == str(runtime_dir)
    assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={runtime_dir / 'bus'}"


def test_parse_monitors_reads_xrandr_geometry():
    output = """Monitors: 2
 0: +*DP-4 2560/597x1440/336+0+0  DP-4
 1: +HDMI-0 2560/526x1440/296+2560+0  HDMI-0
"""

    assert overlay._parse_monitors(output) == [
        (0, 0, 2560, 1440),
        (2560, 0, 2560, 1440),
    ]


def test_overlay_position_uses_top_left_of_rightmost_monitor(monkeypatch):
    monkeypatch.setattr(
        overlay,
        "_active_monitors",
        lambda: [(0, 0, 2560, 1440), (2560, 0, 2560, 1440)],
    )

    assert overlay._overlay_position() == (2584, 24)


def test_overlay_position_falls_back_to_desktop_top_left(monkeypatch):
    monkeypatch.setattr(overlay, "_active_monitors", lambda: [])

    assert overlay._overlay_position() == (24, 24)


def test_stopped_playback_remains_visible_longer():
    assert overlay._completion_visibility_ms("stopped") == 15000
    assert overlay._completion_visibility_ms("aplay") == overlay.DONE_VISIBLE_MS


def test_window_height_grows_with_content_and_stays_on_screen():
    assert overlay._window_height(90, 1080) == overlay.WINDOW_HEIGHT
    assert overlay._window_height(420, 1080) == 420
    assert overlay._window_height(1200, 1080) == 1032
