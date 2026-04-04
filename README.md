# Koe 声

**Your voice, your words. Nothing leaves your machine.**

Koe is a free, open-source, fully offline voice-to-text tool for Windows. Hold `Ctrl+Space`, speak naturally, release — clean text appears wherever your cursor is. No account, no cloud, no subscription.

Koe does what Wispr Flow and Vowen.ai do — but locally, privately, and for free.

---

## What Koe Does

- **Hold-to-talk**: Hold `Ctrl+Space` → speak → release → text appears in any app
- **AI cleanup**: Removes filler words, fixes grammar, adds punctuation — without turning your voice into AI slop. Your voice stays yours.
- **Two output modes**: Auto-type into focused field, or copy to clipboard (toggle with `Ctrl+Shift+Space`)
- **System tray app**: Lightweight, always ready, never in your way
- **Fully offline**: Whisper STT + local LLM cleanup. Zero network calls. Zero telemetry.
- **GPU-accelerated but efficient**: Uses your NVIDIA GPU only during transcription, then releases VRAM

---

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/koe.git
cd koe

# Install (requires Python 3.10+)
pip install -e .

# First run (downloads models on first launch, ~1-2GB)
koe
```

Koe will appear in your system tray. Hold `Ctrl+Space` and start talking.

---

## Requirements

- Windows 10/11
- Python 3.10+
- NVIDIA GPU with CUDA support (recommended) — also works on CPU, just slower
- ~2GB disk for models (downloaded once on first run)

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    System Tray UI                     │
│              (pystray + tray icon states)             │
├─────────────────────────────────────────────────────┤
│                   Hotkey Listener                     │
│           (Ctrl+Space hold-to-talk via keyboard)     │
├──────────────┬──────────────────┬───────────────────┤
│ Audio Capture │   Whisper STT    │   AI Text Cleanup  │
│ (sounddevice) │ (faster-whisper) │  (local LLM/rules) │
├──────────────┴──────────────────┴───────────────────┤
│                   Output Engine                       │
│        (keystroke injection / clipboard paste)        │
└─────────────────────────────────────────────────────┘
```

### Core Modules

| Module | File | What it does |
|--------|------|-------------|
| **Tray App** | `koe/app.py` | System tray icon, state management, settings menu |
| **Hotkey** | `koe/hotkey.py` | Global Ctrl+Space hold detection, press/release events |
| **Audio** | `koe/audio.py` | Mic capture via sounddevice, WAV buffer management |
| **Transcriber** | `koe/transcriber.py` | faster-whisper inference, model loading, GPU management |
| **Cleaner** | `koe/cleaner.py` | AI text cleanup — filler removal, grammar, punctuation |
| **Output** | `koe/output.py` | Keystroke injection (win32) or clipboard paste |
| **Config** | `koe/config.py` | TOML config loading, defaults, validation |
| **Overlay** | `koe/overlay.py` | Minimal recording/processing indicator overlay |

---

## Configuration

Koe uses a simple TOML config at `~/.koe/config.toml`:

```toml
[hotkey]
trigger = "ctrl+space"          # Hold-to-talk key combo
clipboard_toggle = "ctrl+shift+space"  # Switch between type/clipboard mode

[audio]
sample_rate = 16000
silence_threshold = 0.01        # Auto-trim silence at start/end
device = "default"              # Or specify mic device name

[transcription]
model = "base"                  # tiny | base | small | medium | large-v3
language = "en"                 # Or "auto" for detection
device = "cuda"                 # cuda | cpu
compute_type = "int8_float16"   # Efficient: int8 on GPU, float16 for attention

[cleanup]
enabled = true
mode = "rules"                  # "rules" (fast, no model) | "llm" (local LLM cleanup)
remove_fillers = true           # Remove um, uh, like, you know
fix_punctuation = true
fix_grammar = true
preserve_style = true           # Don't make it sound corporate/AI

[output]
default_mode = "type"           # "type" (keystrokes) | "clipboard"
typing_speed = 0                # 0 = instant, >0 = simulated typing delay (ms)

[ui]
show_overlay = true             # Show recording indicator
overlay_position = "top-right"
sound_feedback = true           # Subtle sound on start/stop recording
```

---

## How AI Cleanup Works

Koe's cleanup is opinionated: it makes your speech readable **without** making it sound like ChatGPT wrote it.

**What it does:**
- Removes filler words (um, uh, like, you know, basically, I mean)
- Adds proper punctuation and capitalization
- Fixes obvious grammar (subject-verb agreement, tense consistency)
- Joins fragmented thoughts into clean sentences
- Preserves your word choices, slang, and tone

**What it doesn't do:**
- Rewrite your sentences in "professional" language
- Add words you didn't say
- Change casual tone to formal
- Make everything sound like a LinkedIn post

Two modes:
1. **Rules mode** (default): Fast regex + rule-based cleanup. Zero extra model overhead. Handles 90% of cases.
2. **LLM mode**: Uses a small local LLM (phi-3-mini or similar via llama-cpp-python) for smarter cleanup. More accurate but uses more resources.

---

## Privacy

Koe makes **zero network requests**. Ever.

- All speech processing happens on your machine
- No telemetry, no analytics, no crash reporting
- No account required
- Models are downloaded once and cached locally
- Audio buffers are discarded immediately after transcription
- No logs of your transcriptions are kept

You can verify this: Koe has no network-related imports. Run it behind a firewall. Check it yourself.

---

## Roadmap

- [x] Core hold-to-talk → transcribe → type pipeline
- [x] System tray with state indicators
- [x] TOML configuration
- [x] Rule-based text cleanup
- [ ] Recording overlay indicator
- [ ] Sound feedback on record start/stop
- [ ] LLM-based cleanup mode
- [ ] Custom vocabulary / personal dictionary
- [ ] Streaming transcription (live text while speaking)
- [ ] Multi-language support
- [ ] Whisper model auto-selection based on GPU VRAM

---

## License

MIT — do whatever you want with it.

---

## Why "Koe"?

声 (koe) means "voice" in Japanese. Simple, clean, to the point.
