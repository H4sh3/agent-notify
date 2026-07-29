from __future__ import annotations

import sys

from tts_mcp.preferences import set_tts_enabled, tts_enabled


def main() -> int:
    action = sys.argv[1].lower() if len(sys.argv) == 2 else ""
    if action in {"on", "enable"}:
        set_tts_enabled(True)
        print("TTS is enabled.")
    elif action in {"off", "disable"}:
        set_tts_enabled(False)
        print("TTS is disabled. Notifications will remain visible.")
    elif action == "status":
        print("TTS is enabled." if tts_enabled() else "TTS is disabled.")
    else:
        print("Usage: tts-config {on|off|status}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
