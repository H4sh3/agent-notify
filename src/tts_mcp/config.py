from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

SERVER_HEADER = re.compile(r'^\s*\[mcp_servers\.(?:tts|"tts"|\'tts\')\]\s*$')
TABLE_HEADER = re.compile(r"^\s*\[")
ENABLED_SETTING = re.compile(r"^(\s*)enabled\s*=\s*(?:true|false)(\s*(?:#.*)?)$")


class ConfigError(RuntimeError):
    pass


def codex_config_path() -> Path:
    configured_home = os.environ.get("CODEX_HOME")
    base = Path(configured_home).expanduser() if configured_home else Path.home() / ".codex"
    return base / "config.toml"


def _server_section(lines: list[str]) -> tuple[int, int]:
    start = next((index for index, line in enumerate(lines) if SERVER_HEADER.match(line)), -1)
    if start < 0:
        raise ConfigError(
            "The 'tts' MCP server is not configured. Run the install command from README.md first."
        )

    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if TABLE_HEADER.match(lines[index])
        ),
        len(lines),
    )
    return start, end


def server_enabled(config_path: Path | None = None) -> bool:
    path = config_path or codex_config_path()
    if not path.is_file():
        raise ConfigError(f"Codex config not found: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = _server_section(lines)
    for line in lines[start + 1 : end]:
        match = ENABLED_SETTING.match(line)
        if match:
            return "true" in line.split("#", 1)[0].lower()
    return True


def set_server_enabled(enabled: bool, config_path: Path | None = None) -> Path:
    path = config_path or codex_config_path()
    if not path.is_file():
        raise ConfigError(f"Codex config not found: {path}")

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    start, end = _server_section([line.rstrip("\r\n") for line in lines])
    value = "true" if enabled else "false"

    for index in range(start + 1, end):
        content = lines[index].rstrip("\r\n")
        ending = lines[index][len(content) :]
        match = ENABLED_SETTING.match(content)
        if match:
            lines[index] = f"{match.group(1)}enabled = {value}{match.group(2)}{ending}"
            break
    else:
        ending = "\r\n" if "\r\n" in original else "\n"
        lines.insert(start + 1, f"enabled = {value}{ending}")

    updated = "".join(lines)
    if updated == original:
        return path

    file_mode = path.stat().st_mode
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".config.toml.",
            delete=False,
        ) as temporary:
            temporary.write(updated)
            temporary_name = temporary.name
        os.chmod(temporary_name, file_mode)
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return path


def main() -> int:
    action = sys.argv[1].lower() if len(sys.argv) == 2 else ""
    try:
        if action in {"on", "enable"}:
            set_server_enabled(True)
            print("TTS is enabled. Restart Codex to apply the change.")
        elif action in {"off", "disable"}:
            set_server_enabled(False)
            print("TTS is disabled. Restart Codex to apply the change.")
        elif action == "status":
            print("TTS is enabled." if server_enabled() else "TTS is disabled.")
        else:
            print("Usage: tts-config {on|off|status}", file=sys.stderr)
            return 2
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
