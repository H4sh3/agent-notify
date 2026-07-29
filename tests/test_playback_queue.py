import threading
import time

from tts_mcp.playback_queue import playback_turn


def test_playback_turns_are_fifo_and_report_waiting_messages(tmp_path):
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    order: list[str] = []
    waiting_counts: list[int] = []

    def first() -> None:
        with playback_turn(tmp_path) as pending_count:
            order.append("first")
            first_entered.set()
            assert release_first.wait(timeout=2)
            waiting_counts.append(pending_count())

    def second() -> None:
        assert first_entered.wait(timeout=2)
        with playback_turn(tmp_path):
            order.append("second")
            second_entered.set()

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    second_thread.start()

    assert first_entered.wait(timeout=2)
    deadline = time.monotonic() + 2
    while not list(tmp_path.glob("*.pending")) and time.monotonic() < deadline:
        time.sleep(0.01)

    assert not second_entered.is_set()
    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert order == ["first", "second"]
    assert waiting_counts == [1]
