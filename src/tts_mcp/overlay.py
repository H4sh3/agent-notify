from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
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
PROGRESS_INTERVAL_MS = 50
DONE_VISIBLE_MS = 900
MUTED_VISIBLE_MS = 15000

BACKGROUND = "#111827"
FOREGROUND = "#f9fafb"
MUTED = "#9ca3af"
START_GREEN = "#22c55e"
END_RED = "#ef4444"
PROGRESS_TRACK = "#1f2937"
PROGRESS_FILL = "#6b7280"
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


def _progress_width(
    total_width: int,
    elapsed_ms: float,
    duration_ms: int,
    initial_fraction: float = 1.0,
) -> int:
    if duration_ms <= 0:
        return 0
    remaining = max(0.0, 1.0 - (elapsed_ms / duration_ms))
    return round(total_width * max(0.0, min(initial_fraction, 1.0)) * remaining)


def _remaining_ms(deadline: float, now: float) -> int:
    return max(1, round((deadline - now) * 1000))


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

    progress = tk.Canvas(
        container,
        height=3,
        bg=PROGRESS_TRACK,
        highlightthickness=0,
    )
    progress.grid(
        row=2,
        column=0,
        columnspan=3,
        sticky="ew",
        padx=(0, 8),
        pady=(12, 0),
    )
    progress_fill = progress.create_rectangle(
        0,
        0,
        WINDOW_WIDTH,
        3,
        fill=PROGRESS_FILL,
        outline="",
    )

    pause_button = tk.Button(
        container,
        text="Ⅱ",
        bg=BACKGROUND,
        fg=MUTED,
        activebackground="#1f2937",
        activeforeground=FOREGROUND,
        font=("TkDefaultFont", 8, "bold"),
        relief="flat",
        borderwidth=0,
        highlightthickness=0,
        padx=6,
        pady=0,
        cursor="hand2",
    )
    pause_button.grid(row=2, column=3, sticky="e", pady=(8, 0))

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
    progress_update: str | None = None
    close_deadline: float | None = None
    close_duration_ms: int | None = None
    paused_remaining_ms: int | None = None
    paused_progress_fraction = 1.0
    auto_close_paused = False
    dismissed = False

    def show_full_progress() -> None:
        width = max(1, progress.winfo_width())
        progress.coords(progress_fill, 0, 0, width, 3)

    def cancel_close_timer(*, reset_progress: bool = True) -> None:
        nonlocal muted_close, progress_update, close_deadline, close_duration_ms
        if muted_close is not None:
            root.after_cancel(muted_close)
            muted_close = None
        if progress_update is not None:
            root.after_cancel(progress_update)
            progress_update = None
        close_deadline = None
        close_duration_ms = None
        if reset_progress:
            show_full_progress()

    def start_close_timer(
        duration_ms: int,
        *,
        initial_fraction: float = 1.0,
    ) -> None:
        nonlocal muted_close, progress_update, close_deadline, close_duration_ms
        nonlocal paused_remaining_ms, paused_progress_fraction
        cancel_close_timer()
        if auto_close_paused:
            paused_remaining_ms = duration_ms
            paused_progress_fraction = initial_fraction
            return

        paused_remaining_ms = None
        started_at = time.monotonic()
        close_deadline = started_at + (duration_ms / 1000)
        close_duration_ms = duration_ms

        def update_progress() -> None:
            nonlocal progress_update
            elapsed_ms = (time.monotonic() - started_at) * 1000
            width = max(1, progress.winfo_width())
            remaining_width = _progress_width(
                width,
                elapsed_ms,
                duration_ms,
                initial_fraction,
            )
            progress.coords(progress_fill, 0, 0, remaining_width, 3)
            if remaining_width > 0:
                progress_update = root.after(PROGRESS_INTERVAL_MS, update_progress)
            else:
                progress_update = None

        muted_close = root.after(duration_ms, root.destroy)
        update_progress()

    def toggle_auto_close() -> None:
        nonlocal auto_close_paused, paused_remaining_ms, paused_progress_fraction
        if not auto_close_paused:
            auto_close_paused = True
            remaining = (
                _remaining_ms(close_deadline, time.monotonic())
                if close_deadline is not None
                else None
            )
            paused_progress_fraction = (
                min(1.0, remaining / close_duration_ms)
                if remaining is not None and close_duration_ms
                else 1.0
            )
            cancel_close_timer(reset_progress=False)
            paused_remaining_ms = remaining
            pause_button.configure(
                text="▶",
                bg="#374151",
                fg=FOREGROUND,
            )
        else:
            auto_close_paused = False
            remaining = paused_remaining_ms
            initial_fraction = paused_progress_fraction
            paused_remaining_ms = None
            paused_progress_fraction = 1.0
            pause_button.configure(
                text="Ⅱ",
                bg=BACKGROUND,
                fg=MUTED,
            )
            if remaining is not None:
                start_close_timer(remaining, initial_fraction=initial_fraction)

    def dismiss() -> None:
        nonlocal dismissed
        dismissed = True
        root.withdraw()
        if not playback_started or result is not None:
            root.destroy()

    pause_button.configure(command=toggle_auto_close)
    close_button.configure(command=dismiss)

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
        nonlocal playback_started, result, muted_close, paused_remaining_ms
        nonlocal paused_progress_fraction
        if playback_started:
            return
        cancel_close_timer()
        paused_remaining_ms = None
        paused_progress_fraction = 1.0
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
        start_close_timer(MUTED_VISIBLE_MS)

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
                start_close_timer(_completion_visibility_ms(result))
            else:
                update_state("ENDED")
                start_close_timer(_completion_visibility_ms(result))
        else:
            update_state("ENDED")
            error = outcome if isinstance(outcome, BaseException) else RuntimeError(str(outcome))
            start_close_timer(DONE_VISIBLE_MS)
        if dismissed:
            root.destroy()

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
