from __future__ import annotations

import contextlib
import os
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

POLL_INTERVAL_SECONDS = 0.05


def state_dir() -> Path:
    configured = os.environ.get("TTS_MCP_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "tts-mcp"


def _lock(file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_EX)


def _unlock(file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def _process_exists(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pending_entries(queue_dir: Path) -> list[Path]:
    entries: list[Path] = []
    for entry in queue_dir.glob("*.pending"):
        try:
            pid = int(entry.name.split("-", 2)[1])
        except (IndexError, ValueError):
            continue
        if _process_exists(pid):
            entries.append(entry)
        else:
            with contextlib.suppress(FileNotFoundError):
                entry.unlink()
    return sorted(entries)


@contextlib.contextmanager
def playback_turn(
    queue_dir: Path | None = None,
) -> Iterator[Callable[[], int]]:
    """Wait for a FIFO playback turn and expose the number waiting behind it."""
    queue_dir = queue_dir or state_dir() / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    entry = queue_dir / (
        f"{time.time_ns():020d}-{os.getpid()}-{uuid.uuid4().hex}.pending"
    )
    entry.touch(exist_ok=False)

    lock_path = queue_dir / "playback.lock"
    with lock_path.open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()

        acquired = False
        try:
            while not acquired:
                _lock(lock_file)
                entries = _pending_entries(queue_dir)
                if entries and entries[0] == entry:
                    entry.unlink()
                    acquired = True
                else:
                    _unlock(lock_file)
                    time.sleep(POLL_INTERVAL_SECONDS)

            def pending_count() -> int:
                return len(_pending_entries(queue_dir))

            yield pending_count
        finally:
            with contextlib.suppress(FileNotFoundError):
                entry.unlink()
            if acquired:
                _unlock(lock_file)
