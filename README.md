# Koe 声

**Your voice, your words. Nothing leaves your machine.**

Koe is a free, open-source, fully offline voice-to-text tool for Windows. Hold `Alt+K`, speak naturally, release — clean text appears wherever your cursor is. No account, no cloud, no subscription.

---

## What it does

- **Hold-to-talk** — Hold `Alt+K` → speak → release → text appears in any app
- **Smart cleanup** — Removes filler words and fixes punctuation without making your voice sound like a ChatGPT response
- **Three output modes** — Write into the focused app and keep copied, paste from clipboard, or type directly
- **Recording overlay** — Minimal animated waveform pill shows when Koe is listening or processing
- **Transcription history** — Every dictation is saved in the UI for easy copy/reuse
- **System tray** — Lightweight, always ready, never in your way
- **Fully offline** — Whisper STT runs locally. Zero network calls after first model download. Zero telemetry.
- **GPU-accelerated** — Uses your NVIDIA GPU during transcription, then releases VRAM immediately

---

## Requirements

- Windows 10 or 11
- Python 3.10+
- NVIDIA GPU with CUDA (recommended) — CPU works too, just slower
- ~500 MB disk space for the default model (downloaded once on first run)

---

## Installation

```bash
git clone https://github.com/giri2five/koe.git
cd koe

pip install -e .
```

On first launch Koe downloads the Whisper model (~500 MB for `small.en`). Subsequent launches are instant.

```bash
koe
```

Koe opens a settings window and appears in your system tray. Hold `Alt+K` and start talking.

---

## Usage

| Action | What happens |
|--------|-------------|
| Hold `Alt+K` | Recording starts, overlay appears |
| Release `Alt+K` | Recording stops, text is transcribed and delivered |
| Click X on window | Hides to system tray |
| Tray → Open Koe | Brings the settings window back |
| Right-click tray icon | Open Koe / Quit |

---

## Settings window

The settings window gives you full control without touching a config file:

- **Microphone** — pick your input device from a dropdown
- **Output mode** — choose how text is delivered to your app
- **Recording overlay** — toggle the animated waveform pill
- **Sound cues** — toggle audio feedback on record start/stop
- **History** — browse and copy every recent dictation
- **Last result** — copy or clear the most recent transcription

---

## Configuration

Koe stores config at `~/.koe/config.toml`. The settings window covers the common options — only edit this file for advanced tweaks.

```toml
[hotkey]
trigger = "alt+k"
clipboard_toggle = ""          # optional secondary hotkey, disabled by default

[audio]
sample_rate = 16000
silence_threshold = 0.01
device = "system_default"
min_duration = 0.3             # ignore taps shorter than this (seconds)
max_duration = 120.0           # safety cutoff

[transcription]
model = "small.en"    # tiny | base | base.en | small | small.en | medium | large-v3
language = "en"       # or "auto" for detection
device = "cuda"       # cuda | cpu
compute_type = "int8_float16"
beam_size = 5

[cleanup]
enabled = true
mode = "rules"         # "rules" (fast, no extra model) | "llm" (local LLM)
remove_fillers = true
fix_punctuation = true

[output]
default_mode = "both"  # "both" | "clipboard" | "type"

[ui]
show_overlay = true
sound_feedback = true
```

### Whisper models

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| `tiny` | ~75 MB | Fastest | Basic |
| `base` / `base.en` | ~150 MB | Fast | Good |
| `small` / `small.en` | ~500 MB | Medium | Better **(default)** |
| `medium` | ~1.5 GB | Slow | Great |
| `large-v3` | ~3 GB | Slowest | Best |

English-only models (`base.en`, `small.en`) are faster and more accurate if you only dictate in English.

---

## How text cleanup works

Koe cleans up your speech without making it sound like AI wrote it.

**What it removes/fixes:**
- Filler words: *um, uh, like, you know, basically, I mean*
- Missing punctuation and capitalisation
- Obvious grammar mistakes

**What it leaves alone:**
- Your word choices and tone
- Casual or informal language
- Anything that sounds like *you*

Two modes:
- **Rules mode** (default) — Fast regex-based cleanup. No extra model needed.
- **LLM mode** — Uses a small local LLM via `llama-cpp-python` for smarter cleanup. Install with `pip install koe[llm]`.

---

## Privacy

Koe makes **zero network requests** after the model is downloaded.

- All processing happens on your machine
- No telemetry, no analytics, no crash reporting
- No account required
- Models are cached locally after the first download
- Audio is discarded immediately after transcription

---

## Roadmap

- [x] Hold-to-talk → transcribe → deliver pipeline
- [x] Settings window UI
- [x] System tray with state indicators
- [x] Rule-based text cleanup
- [x] TOML configuration
- [x] Recording overlay indicator (animated waveform pill)
- [x] Sound feedback on record start/stop
- [x] Transcription history
- [x] Custom app icon
- [ ] LLM cleanup toggle in UI
- [ ] Voice snippets — trigger phrases expand to templates
- [ ] File transcription — `koe --file audio.mp3`
- [ ] Context-aware formatting — detect active app, adjust style
- [ ] Whisper model selector in UI
- [ ] One-click Windows installer (.exe)

---

## License

MIT — do whatever you want with it.

---

## Why "Koe"?

声 (こえ / koe) means "voice" in Japanese.
