# AGENTS.md — Koe Codebase Guide for AI Agents

## What is Koe?

Koe is a free, offline, privacy-first voice-to-text app for Windows. It runs as a system tray application. The user holds Ctrl+Space, speaks, releases, and clean text appears wherever their cursor is.

## Architecture

```
koe/
├── __init__.py        # Package root, version
├── __main__.py        # Entry point (python -m koe)
├── app.py             # Main orchestrator — ties all modules together
├── config.py          # TOML config loading/saving, dataclass schemas
├── audio.py           # Mic recording via sounddevice
├── transcriber.py     # Whisper STT via faster-whisper
├── cleaner.py         # Text cleanup (rule-based + optional LLM)
├── output.py          # Keystroke injection / clipboard paste via win32
├── hotkey.py          # Global hotkey detection via keyboard library
├── overlay.py         # Minimal recording indicator via tkinter
└── assets/            # Icons, sounds (future)
```

## Key Design Decisions

1. **Each module is independent.** You can test `transcriber.py` without `app.py`. Modules communicate via simple function calls, not events or message buses.

2. **No async.** Everything runs in threads. Simpler to reason about, debug, and test on Windows.

3. **Win32 for output.** We use ctypes + SendInput for keystroke injection. This is the most reliable method on Windows and works in any text field including Electron apps.

4. **GPU efficiency.** The Whisper model is loaded once and stays in memory. We use int8_float16 compute type — the best balance of speed and accuracy. VRAM usage stays under 1GB for the base model.

5. **Config is TOML.** Lives at ~/.koe/config.toml. All defaults are sane — first run should just work.

## Testing

Run tests with: `pytest tests/`

Tests should NOT require a GPU or microphone. Mock the hardware interfaces.

## Code Style

- Python 3.10+ (use `X | Y` union types, not `Union[X, Y]`)
- Type hints everywhere
- Docstrings on all public classes and methods
- Logging via `logging.getLogger(__name__)`
- No global mutable state
- f-strings for formatting

## Common Tasks for Agents

### "Add a new feature"
1. Create a new module in `koe/` if it's a new concern
2. Wire it into `app.py`
3. Add config fields to `config.py` if needed
4. Add tests in `tests/`

### "Fix a bug in transcription"
→ Look at `transcriber.py`. The `transcribe()` method is the entry point.

### "Change the cleanup behavior"
→ Look at `cleaner.py`. Rule-based cleanup is in `_clean_with_rules()`.

### "Change the hotkey"
→ `hotkey.py` handles detection. Config is in `config.py` HotkeyConfig.

### "Add a new output method"
→ `output.py`. Add a new method alongside `_type_text` and `_clipboard_paste`.
