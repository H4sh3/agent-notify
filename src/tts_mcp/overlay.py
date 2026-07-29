from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from tts_mcp.playback_queue import playback_turn
from tts_mcp.preferences import set_tts_enabled, tts_enabled
from tts_mcp.tts import play_audio_file

Playback = Callable[[Path], str]
PendingCount = Callable[[], int]

WINDOW_WIDTH = 420
WINDOW_HEIGHT = 128
SCREEN_MARGIN = 24
POLL_INTERVAL_MS = 50
DONE_VISIBLE_MS = 900
MUTED_VISIBLE_MS = 15000

BACKGROUND = "#111827"
FOREGROUND = "#f9fafb"
MUTED = "#9ca3af"
START_GREEN = "#22c55e"
END_RED = "#ef4444"
MONITOR_PATTERN = re.compile(
    r"^\s*\d+:\s+\S+\s+"
    r"(\d+)/\d+x(\d+)/\d+([+-]\d+)([+-]\d+)\s"
)


def overlay_enabled() -> bool:
    value = os.environ.get("TTS_MCP_OVERLAY", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _completion_visibility_ms(player: str) -> int:
    return MUTED_VISIBLE_MS if player == "stopped" else DONE_VISIBLE_MS


def _window_height(requested_height: int, screen_height: int) -> int:
    available_height = max(WINDOW_HEIGHT, screen_height - (SCREEN_MARGIN * 2))
    return max(WINDOW_HEIGHT, min(requested_height, available_height))


def play_message(
    message: str,
    audio_path: Path,
    *,
    playback: Playback = play_audio_file,
) -> str:
    """Show a status overlay while playing audio, with an audio-only fallback."""
    with playback_turn() as pending_count:
        if not overlay_enabled():
            return playback(audio_path) if tts_enabled() else "tts-disabled"

        try:
            return _play_with_tk(message, audio_path, playback, pending_count)
        except _OverlayUnavailable:
            return playback(audio_path) if tts_enabled() else "tts-disabled"


class _OverlayUnavailable(RuntimeError):
    pass


def _find_x11_display(socket_dir: Path = Path("/tmp/.X11-unix")) -> str | None:
    try:
        sockets = sorted(socket_dir.glob("X*"))
    except OSError:
        return None
    for socket in sockets:
        number = socket.name.removeprefix("X")
        if number.isdigit() and socket.is_socket():
            return f":{number}"
    return None


def _prepare_graphical_environment() -> None:
    if sys.platform != "linux":
        return

    runtime_dir = Path(f"/run/user/{os.getuid()}")
    if not os.environ.get("XDG_RUNTIME_DIR") and runtime_dir.is_dir():
        os.environ["XDG_RUNTIME_DIR"] = str(runtime_dir)

    if not os.environ.get("DISPLAY"):
        display = _find_x11_display()
        if display is not None:
            os.environ["DISPLAY"] = display

    if not os.environ.get("XAUTHORITY"):
        authority = runtime_dir / "gdm" / "Xauthority"
        if authority.is_file():
            os.environ["XAUTHORITY"] = str(authority)

    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        bus = runtime_dir / "bus"
        if bus.exists():
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"


def _parse_monitors(output: str) -> list[tuple[int, int, int, int]]:
    monitors: list[tuple[int, int, int, int]] = []
    for line in output.splitlines():
        match = MONITOR_PATTERN.match(line)
        if match is not None:
            width, height, x, y = (int(value) for value in match.groups())
            monitors.append((x, y, width, height))
    return monitors


def _active_monitors() -> list[tuple[int, int, int, int]]:
    try:
        completed = subprocess.run(
            ["xrandr", "--listactivemonitors"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return _parse_monitors(completed.stdout)


def _overlay_position() -> tuple[int, int]:
    monitors = _active_monitors()
    if not monitors:
        return SCREEN_MARGIN, SCREEN_MARGIN
    x, y, _, _ = max(monitors, key=lambda monitor: monitor[0] + monitor[2])
    return x + SCREEN_MARGIN, y + SCREEN_MARGIN


def _play_with_tk(
    message: str,
    audio_path: Path,
    playback: Playback,
    pending_count: PendingCount,
) -> str:
    _prepare_graphical_environment()
    try:
        import tkinter as tk
    except ImportError as exc:
        raise _OverlayUnavailable("Tk is not installed.") from exc

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise _OverlayUnavailable("No graphical display is available.") from exc

    root.title("Codex voice message")
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=BACKGROUND)

    container = tk.Frame(
        root,
        bg=BACKGROUND,
        highlightbackground="#374151",
        highlightthickness=1,
        padx=16,
        pady=14,
    )
    container.pack(fill="both", expand=True)

    status = tk.Canvas(
        container,
        width=22,
        height=22,
        bg=BACKGROUND,
        highlightthickness=0,
    )
    status.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 12), pady=(2, 0))
    square = status.create_rectangle(2, 2, 20, 20, fill=START_GREEN, outline="")

    state_label = tk.Label(
        container,
        text="PLAYING",
        bg=BACKGROUND,
        fg=MUTED,
        font=("TkDefaultFont", 9, "bold"),
        anchor="w",
    )
    state_label.grid(row=0, column=1, sticky="ew")

    voice_enabled = tts_enabled()
    playback_started = False
    muted_close: str | None = None

    toggle_button = tk.Button(
        container,
        text="TTS ON" if voice_enabled else "TTS OFF",
        bg="#166534" if voice_enabled else "#374151",
        fg=FOREGROUND,
        activebackground="#15803d" if voice_enabled else "#4b5563",
        activeforeground=FOREGROUND,
        font=("TkDefaultFont", 8, "bold"),
        relief="flat",
        borderwidth=0,
        highlightthickness=0,
        padx=8,
        pady=3,
        cursor="hand2",
    )
    toggle_button.grid(row=0, column=2, sticky="ne", padx=(8, 0))

    close_button = tk.Button(
        container,
        text="×",
        command=root.withdraw,
        bg=BACKGROUND,
        fg=MUTED,
        activebackground="#1f2937",
        activeforeground=FOREGROUND,
        font=("TkDefaultFont", 12, "bold"),
        relief="flat",
        borderwidth=0,
        highlightthickness=0,
        padx=5,
        pady=0,
        cursor="hand2",
    )
    close_button.grid(row=0, column=3, sticky="ne", padx=(6, 0))

    message_label = tk.Label(
        container,
        text=" ".join(message.split()),
        bg=BACKGROUND,
        fg=FOREGROUND,
        font=("TkDefaultFont", 11),
        justify="left",
        anchor="nw",
        wraplength=WINDOW_WIDTH - 84,
    )
    message_label.grid(
        row=1,
        column=1,
        columnspan=3,
        sticky="nsew",
        pady=(7, 0),
    )
    container.columnconfigure(1, weight=1)
    container.rowconfigure(1, weight=1)

    root.update_idletasks()
    height = _window_height(container.winfo_reqheight(), root.winfo_screenheight())
    x, y = _overlay_position()
    root.geometry(f"{WINDOW_WIDTH}x{height}+{x}+{y}")
    root.deiconify()

    outcomes: queue.Queue[tuple[bool, str | BaseException]] = queue.Queue(maxsize=1)
    stop_playback = threading.Event()
    result: str | None = "tts-disabled" if not voice_enabled else None
    error: BaseException | None = None

    def update_state(text: str) -> None:
        waiting = pending_count()
        suffix = f" • {waiting} QUEUED" if waiting else ""
        state_label.configure(text=f"{text}{suffix}")

    def run_playback() -> None:
        try:
            if playback is play_audio_file:
                outcome = playback(audio_path, stop_event=stop_playback)
            else:
                outcome = playback(audio_path)
            outcomes.put((True, outcome))
        except BaseException as exc:
            outcomes.put((False, exc))

    def start_playback() -> None:
        nonlocal playback_started, result, muted_close
        if playback_started:
            return
        if muted_close is not None:
            root.after_cancel(muted_close)
            muted_close = None
        playback_started = True
        result = None
        status.itemconfigure(square, fill=START_GREEN)
        update_state("PLAYING")
        threading.Thread(target=run_playback, name="tts-playback", daemon=True).start()
        root.after(POLL_INTERVAL_MS, poll_playback)

    def close_muted() -> None:
        nonlocal muted_close
        status.itemconfigure(square, fill=END_RED)
        update_state("MUTED")
        muted_close = root.after(MUTED_VISIBLE_MS, root.destroy)

    def toggle_voice() -> None:
        nonlocal voice_enabled
        voice_enabled = not voice_enabled
        set_tts_enabled(voice_enabled)
        toggle_button.configure(
            text="TTS ON" if voice_enabled else "TTS OFF",
            bg="#166534" if voice_enabled else "#374151",
            activebackground="#15803d" if voice_enabled else "#4b5563",
        )
        if voice_enabled and not playback_started:
            start_playback()
        elif not voice_enabled and playback_started:
            stop_playback.set()
            update_state("STOPPING")

    toggle_button.configure(command=toggle_voice)

    def poll_playback() -> None:
        nonlocal playback_started, result, error, muted_close
        try:
            succeeded, outcome = outcomes.get_nowait()
        except queue.Empty:
            update_state("PLAYING" if voice_enabled else "STOPPING")
            root.after(POLL_INTERVAL_MS, poll_playback)
            return

        status.itemconfigure(square, fill=END_RED)
        if succeeded:
            result = str(outcome)
            if result == "stopped":
                playback_started = False
                stop_playback.clear()
                update_state("MUTED")
                muted_close = root.after(_completion_visibility_ms(result), root.destroy)
            else:
                update_state("ENDED")
                root.after(_completion_visibility_ms(result), root.destroy)
        else:
            update_state("ENDED")
            error = outcome if isinstance(outcome, BaseException) else RuntimeError(str(outcome))
            root.after(DONE_VISIBLE_MS, root.destroy)

    if voice_enabled:
        start_playback()
    else:
        close_muted()
    root.mainloop()

    if error is not None:
        raise error
    if result is None:
        raise RuntimeError("The message overlay closed before playback completed.")
    return result
