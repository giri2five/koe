# Koe 声

**Your voice, your words. Nothing leaves your machine.**

Koe is a free, open-source, fully offline voice-to-text tool for Windows. Hold `Ctrl+Space`, speak naturally, release — clean text appears wherever your cursor is. No account, no cloud, no subscription.

---

## What it does

- **Hold-to-talk** — Hold `Alt+K` → speak → release → text appears in any app
- **AI cleanup** — Removes filler words, fixes grammar and punctuation without making your voice sound like a ChatGPT response
- **Two output modes** — Auto-type into the focused field, or copy to clipboard (toggle with `Ctrl+Shift+Space`)
- **System tray** — Lightweight, always ready, never in your way
- **Fully offline** — Whisper STT runs locally. Zero network calls. Zero telemetry.
- **GPU-accelerated** — Uses your NVIDIA GPU during transcription, then releases VRAM immediately

---

## Requirements

- Windows 10 or 11
- Python 3.10+
- NVIDIA GPU with CUDA (recommended) — CPU works too, just slower
- ~2 GB disk space for models (downloaded once on first run)

---

## Installation

```bash
git clone https://github.com/giri2five/koe.git
cd koe

pip install -e .
```

That's it. On first launch, Koe downloads the Whisper model (~150 MB for `base`). Subsequent launches are instant.

```bash
koe
```

Koe appears in your system tray. Hold `Ctrl+Space` and start talking.

---

## Usage

| Action | What happens |
|--------|-------------|
| Hold `Alt+K` | Recording starts |
| Release `Alt+K` | Recording stops, text is transcribed and delivered |
| Right-click tray icon | Change model, output mode, open settings, quit |

---

## Configuration

Koe creates a config file at `~/.koe/config.toml` on first run. All settings have sane defaults — you don't need to touch it.

```toml
[hotkey]
trigger = "alt+k"
clipboard_toggle = ""          # optional, disabled by default

[audio]
sample_rate = 16000
silence_threshold = 0.01
device = "default"

[transcription]
model = "base"        # tiny | base | small | medium | large-v3
language = "en"       # or "auto" for detection
device = "cuda"       # cuda | cpu

[cleanup]
enabled = true
mode = "rules"        # "rules" (fast) | "llm" (local LLM, more accurate)
remove_fillers = true
fix_punctuation = true
fix_grammar = true

[output]
default_mode = "type" # "type" | "clipboard"

[ui]
show_overlay = true
sound_feedback = true
```

### Whisper models

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| `tiny` | ~75 MB | Fastest | Basic |
| `base` | ~150 MB | Fast | Good (default) |
| `small` | ~500 MB | Medium | Better |
| `medium` | ~1.5 GB | Slow | Great |
| `large-v3` | ~3 GB | Slowest | Best |

Pick based on your GPU/CPU. `base` is the right default for most people.

---

## How text cleanup works

Koe cleans up your speech without making it sound like AI wrote it.

**What it removes/fixes:**
- Filler words: *um, uh, like, you know, basically, I mean*
- Missing punctuation and capitalization
- Obvious grammar mistakes

**What it leaves alone:**
- Your word choices and tone
- Casual or informal language
- Anything that sounds like *you*

Two modes:
- **Rules mode** (default) — Fast regex-based cleanup. No extra model needed. Handles 90% of cases.
- **LLM mode** — Uses a small local LLM via `llama-cpp-python` for smarter cleanup. Install with `pip install koe[llm]`.

---

## Privacy

Koe makes **zero network requests**. Ever.

- All processing happens on your machine
- No telemetry, no analytics, no crash reporting
- No account required
- Models are cached locally after the first download
- Audio is discarded immediately after transcription
- No transcription logs are kept

You can verify this yourself — Koe has no network-related imports.

---

## Roadmap

- [x] Hold-to-talk → transcribe → deliver pipeline
- [x] System tray with state indicators
- [x] Rule-based text cleanup
- [x] TOML configuration
- [x] Recording overlay indicator
- [x] Sound feedback on record start/stop
- [ ] LLM-based cleanup mode
- [ ] Whisper model auto-selection based on VRAM
- [ ] Custom vocabulary / personal dictionary
- [ ] Streaming transcription (live preview while speaking)
- [ ] Multi-language support
- [ ] One-click Windows installer (.exe)

---

## License

MIT — do whatever you want with it.

---

## Why "Koe"?

声 (こえ / koe) means "voice" in Japanese.
