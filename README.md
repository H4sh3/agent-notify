<p align="center">
  <img src="assets/tts-mcp-logo.svg" alt="tts-mcp" width="160">
</p>

Local spoken notifications for Codex. Each message plays through your speakers
and appears in a small always-on-top overlay.

## Install

Requires Python 3.11 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
codex mcp add tts -- "$(pwd)/.venv/bin/tts-mcp"
```

Restart Codex, then run `/mcp` to check that `tts` is connected. The voice model
downloads automatically the first time it speaks.

## Turn TTS on or off

```bash
uv run tts-config off
uv run tts-config on
uv run tts-config status
```

Restart Codex after switching it on or off.

## Try it

```bash
uv run tts-notify \
  '{"type":"agent-turn-complete","last-assistant-message":"TTS is ready."}'
```

## Test

```bash
uv run pytest
```

## Optional settings

Set these environment variables when registering the server with
`codex mcp add ... --env NAME=VALUE`:

- `TTS_MCP_MODEL` — Coqui model name
- `TTS_MCP_SPEAKER` — speaker ID for a multi-speaker model
- `TTS_MCP_OUTPUT_DIR` — directory for cached WAV files
- `TTS_MCP_OVERLAY=off` — play audio without the overlay

The default model is `tts_models/en/jenny/jenny`. Audio continues to work when
no graphical display is available.
