from pathlib import Path

import pytest

from tts_mcp.config import ConfigError, server_enabled, set_server_enabled


def write_config(path: Path, enabled: str = "") -> None:
    path.write_text(
        "[mcp_servers.other]\n"
        'command = "other"\n'
        "\n"
        "[mcp_servers.tts]\n"
        f"{enabled}"
        'command = "/project/.venv/bin/tts-mcp"\n'
        "\n"
        "[features]\n"
        "web_search = true\n",
        encoding="utf-8",
    )


def test_tts_is_enabled_by_default(tmp_path):
    config = tmp_path / "config.toml"
    write_config(config)

    assert server_enabled(config) is True


def test_disable_and_enable_tts_without_changing_other_config(tmp_path):
    config = tmp_path / "config.toml"
    write_config(config)

    set_server_enabled(False, config)
    assert server_enabled(config) is False
    assert "[features]\nweb_search = true" in config.read_text(encoding="utf-8")

    set_server_enabled(True, config)
    assert server_enabled(config) is True
    assert config.read_text(encoding="utf-8").count("enabled =") == 1


def test_updates_existing_setting_and_preserves_comment(tmp_path):
    config = tmp_path / "config.toml"
    write_config(config, "enabled = false # voice toggle\n")

    set_server_enabled(True, config)

    assert "enabled = true # voice toggle" in config.read_text(encoding="utf-8")


def test_missing_tts_server_is_reported(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[features]\nweb_search = true\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="not configured"):
        set_server_enabled(False, config)
