from tts_mcp import setup


def test_prepare_and_test_loads_model_synthesizes_and_plays(monkeypatch, tmp_path):
    audio_path = tmp_path / "setup.wav"
    calls = []
    monkeypatch.setattr(setup, "load_model", lambda: "test-model")
    monkeypatch.setattr(
        setup,
        "synthesize_text",
        lambda message, path: calls.append(("synthesize", message, path)),
    )
    monkeypatch.setattr(
        setup,
        "play_message",
        lambda message, path: calls.append(("play", message, path)) or "test-player",
    )

    result = setup.prepare_and_test(audio_path)

    assert result == "test-player"
    assert calls == [
        ("synthesize", setup.TEST_MESSAGE, audio_path),
        ("play", setup.TEST_MESSAGE, audio_path),
    ]


def test_prepare_and_test_reuses_cached_audio(monkeypatch, tmp_path):
    audio_path = tmp_path / "setup.wav"
    audio_path.write_bytes(b"wave")
    monkeypatch.setattr(setup, "load_model", lambda: "test-model")
    monkeypatch.setattr(
        setup,
        "synthesize_text",
        lambda *args: (_ for _ in ()).throw(AssertionError("should use cache")),
    )
    monkeypatch.setattr(setup, "play_message", lambda message, path: "tts-disabled")

    assert setup.prepare_and_test(audio_path) == "tts-disabled"
