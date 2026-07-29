# Repository guidance

## Product intent

This project is a local spoken-message experience, not only an MCP wrapper
around a text-to-speech engine. A played message should also be visible in a
small, always-on-top overlay at the right side of the screen.

The overlay uses an unambiguous status square:

- green means the message has started and is currently playing;
- red means playback has ended.

Keep the overlay compact, readable, and useful without interaction. Audio must
still work when no graphical display is available.

## Implementation conventions

- Keep stdout reserved for JSON-RPC in the stdio MCP server.
- Prefer Python standard-library UI and process facilities unless a new
  dependency is clearly justified.
- Keep synthesis, audio playback, and presentation separable so each can be
  tested without loading a TTS model or opening a real window.
- Preserve cached WAV generation and audio-only fallback behavior.
- Any background notifier process must remain detached from Codex.

## Validation

Run the full test suite after behavioral changes:

```bash
uv run pytest
```

For overlay changes, also perform a manual desktop check with:

```bash
uv run tts-notify \
  '{"type":"agent-turn-complete","last-assistant-message":"Overlay check complete."}'
```
