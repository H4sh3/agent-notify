import json

from tts_mcp.preferences import set_tts_enabled, tts_enabled


def test_tts_is_enabled_by_default(tmp_path):
    assert tts_enabled(tmp_path / "missing.json") is True


def test_tts_preference_is_persisted(tmp_path):
    settings = tmp_path / "settings.json"

    set_tts_enabled(False, settings)
    assert tts_enabled(settings) is False
    assert json.loads(settings.read_text(encoding="utf-8")) == {"tts_enabled": False}

    set_tts_enabled(True, settings)
    assert tts_enabled(settings) is True


def test_other_settings_are_preserved(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"theme": "dark"}\n', encoding="utf-8")

    set_tts_enabled(False, settings)

    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "theme": "dark",
        "tts_enabled": False,
    }


def test_invalid_settings_use_enabled_default(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("not json", encoding="utf-8")

    assert tts_enabled(settings) is True
