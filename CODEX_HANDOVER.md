# CODEX_HANDOVER.md — Build Koe: Complete UI/UX + Implementation Guide

> **For Codex / AI coding agent.** This document contains everything needed to build Koe's
> UI/UX layer from scratch. Read this entire document before writing any code.

---

## 1. WHAT YOU'RE BUILDING

Koe (声) is a free, offline, privacy-first voice-to-text Windows app. The user holds
Ctrl+Space, speaks, releases, and clean text appears wherever their cursor is.

The UI must feel like it was designed by someone who actually uses Wispr Flow and
SuperWhisper daily and got fed up with their limitations. Not a developer side-project.
Not "good enough." Actually beautiful. Actually thoughtful.

---

## 2. COMPETITIVE LANDSCAPE — WHAT EXISTS AND WHAT TO BEAT

### Wispr Flow (paid, $8-15/month)
- Clean editorial design. Minimalist overlay near cursor. Calm palette.
- Wispr's rebrand used Figtree + editorial serif, soft neutrals, green accents.
- Their philosophy: "purposefully editorial" — every space serves emotional or cognitive clarity.
- Recording indicator is subtle — small pill near cursor, not intrusive.
- Weakness: subscription-locked, cloud-dependent for AI features, support is terrible.

### Vowen.ai (free, open source)
- Menu bar / system tray app. Hold Fn to dictate, Option+Shift for AI mode.
- More utilitarian UI — functional but not beautiful.
- Strength: free forever, local processing, utilities (PDF merge, timers, etc.)
- Weakness: UI is developer-grade, not designer-grade. Feels like a tool, not an experience.

### SuperWhisper (macOS, $8.49/month or lifetime)
- Best-in-class macOS dictation UX. Small waveform overlay while recording.
- Custom modes, multiple AI models, beautiful native integration.
- Fast Company Innovation by Design Awards finalist (2025).
- "Clean, minimalist design that integrates smoothly with macOS."
- Weakness: macOS only. No Windows version. Paid.

### JustDictate / Turbo-Whisper (OSS clones)
- JustDictate: dark translucent floating window with waveform animation bars
- Turbo-Whisper: configurable waveform color (#00ff88), dark background (#1a1a2e)
- Both prove the waveform-overlay pattern works well for recording feedback

### What ALL of them get wrong:
1. Settings UIs are either ugly tkinter or buried in JSON files
2. No visual personality — they all look like dev tools
3. Overlay indicators are either too big or too subtle
4. No satisfying micro-interactions (sound, animation, state transitions)
5. The "processing" state is always an afterthought

---

## 3. KOE'S DESIGN PHILOSOPHY

**One sentence:** Koe should feel like a high-end audio tool that happens to do voice-to-text.

### Core Principles:
1. **Invisible when idle.** System tray icon. Nothing else. Zero visual footprint.
2. **Beautiful when active.** When recording, a small floating overlay appears near the
   cursor with a live waveform. Dark, translucent, with a warm accent color. It should
   feel like a tiny recording studio materialized on your screen.
3. **Satisfying feedback loops.** Subtle sound on record start (soft click/blip). Different
   tone on stop. The overlay animates in and out, not just appears/disappears.
4. **Respect for attention.** Never steal focus. Never block interaction. Click-through
   overlay. No notifications. No popups. No "tips."
5. **Dark by default.** This is a tool for people who work. Dark translucent glass
   aesthetic. No light mode needed for v1.

### Design Language:
- **Colors:** Deep charcoal base (#0d0d12), warm coral/vermillion accent (#ff4f3d),
  secondary cool white (#e8e6e1), processing amber (#ffb347). No blue. No purple. No green.
  These are overused in AI tools. Coral/vermillion says "audio, warmth, voice" — not "tech startup."
- **Typography:** No need for fancy fonts in the overlay — it's tiny. Use Segoe UI Variable
  (Windows 11 system font) at the right weights. The overlay text should be 11-12px,
  semibold. If there's a settings window, use the same font family but at larger sizes.
- **Shape language:** Rounded rectangles with 12-16px radius. Soft shadows. The overlay
  should feel like a floating pill, not a box.
- **Motion:** Ease-in-out curves. 200ms for show/hide. Waveform bars animate at 60fps
  from real audio RMS levels. Processing state uses a smooth left-to-right shimmer, not
  a spinner.

---

## 4. UI COMPONENTS — DETAILED SPECS

### 4A. SYSTEM TRAY ICON

**Size:** 16x16 and 32x32 (Windows auto-scales)

**Design:**
- Default state: A minimal sound wave icon — 3 vertical bars of varying heights in
  coral (#ff4f3d) on transparent background. Think of it as a tiny audio waveform frozen
  in time. NOT a microphone icon (overused). NOT a circle with a letter.
- Recording state: The bars animate/pulse subtly (if possible with pystray, otherwise
  swap to a filled version). The coral becomes brighter/more saturated.
- Processing state: The bars become amber (#ffb347).
- Error state: Bars become grey (#666).

**Context Menu (right-click):**
```
┌──────────────────────────────┐
│  Koe 声                      │
│  ─────────────────────────── │
│  Mode: Type into field    ▸  │
│  Model: base              ▸  │
│  ─────────────────────────── │
│  Settings...                 │
│  ─────────────────────────── │
│  Quit                        │
└──────────────────────────────┘
```

Mode submenu: "Type into field" / "Copy to clipboard"
Model submenu: "tiny" / "base" / "small" / "medium" / "large-v3"
Settings opens the settings window (if built) or opens the config.toml in Notepad.

### 4B. RECORDING OVERLAY — THE HERO UI ELEMENT

This is what makes Koe feel premium. It's a small floating window that appears when
the user starts recording.

**Behavior:**
1. User presses Ctrl+Space
2. After 100ms (debounce to avoid flicker on accidental taps), the overlay fades in
3. Overlay appears near the system tray area (bottom-right on Windows) — NOT near cursor
   (cursor-following is distracting and technically fragile on Windows)
4. While recording, a live waveform animates based on audio input levels
5. User releases Ctrl+Space
6. Overlay transitions to "processing" state (waveform freezes, shimmer effect)
7. Text is delivered
8. Overlay fades out

**Visual Design:**
```
┌─────────────────────────────────────────┐
│                                         │
│   ▎▍▊█▊▍▎▏  ▎▍█▊▍▎   ▍▊█▍▎           │
│                                         │
│   ● 0:03                                │
│                                         │
└─────────────────────────────────────────┘
```

- **Size:** ~280px wide x ~80px tall. Small. Not intrusive.
- **Background:** Semi-transparent dark (#0d0d12 at 85% opacity) with blur effect
  (Windows acrylic/mica if available, otherwise just transparency).
- **Waveform:** 40-60 vertical bars, animated from real-time audio RMS values.
  Bars are coral (#ff4f3d) with a subtle glow. Bar width: 3px, gap: 2px. Height
  varies 4px to 40px based on audio level. Bars should have rounded tops (2px radius).
  Animation: smooth interpolation between frames, not jumpy.
- **Recording indicator:** Small filled circle (●) in coral, 6px diameter. Gently
  pulses (opacity 0.6 to 1.0, 1.5s cycle). Next to it, recording duration in
  seconds (e.g., "0:03") in #e8e6e1, 11px, Segoe UI.
- **Corner radius:** 16px on the overlay container.
- **Shadow:** Subtle drop shadow (0 4px 20px rgba(0,0,0,0.4)).
- **Position:** Bottom-right corner of the screen, 20px from edges, above the taskbar.
- **Click-through:** The overlay must NOT capture mouse events. The user should be able
  to click through it. On Windows, use WS_EX_LAYERED | WS_EX_TRANSPARENT extended
  window styles via win32api.

**Processing state:**
- Waveform bars freeze at their last position
- A subtle left-to-right shimmer/gradient sweeps across them (like a skeleton loading state)
- The recording indicator dot changes to amber (#ffb347) and stops pulsing
- Duration text changes to "Processing..."
- This state lasts until text is delivered

**Animations:**
- Fade in: 200ms ease-out (opacity 0 to 1, translate Y from +10px to 0)
- Fade out: 300ms ease-in (opacity 1 to 0, translate Y from 0 to +10px)
- Waveform: 60fps update rate, bars interpolate smoothly (use linear interpolation
  between current height and target height with a lerp factor of 0.3)

### 4C. SOUND FEEDBACK

Two very short audio cues. Generate them programmatically (no external files needed).

**Start sound (on Ctrl+Space press):**
- A soft, warm "blip" — a quick sine wave at 880Hz (A5) with a fast attack (5ms)
  and short decay (80ms). Volume: quiet (0.15 amplitude). Think of the macOS
  screenshot sound but even more subtle.
- Envelope: linear attack 5ms, exponential decay 80ms
- Apply a gentle low-pass filter to soften it

**Stop sound (on Ctrl+Space release):**
- A descending two-tone: 660Hz for 40ms then 440Hz for 60ms. Same quiet volume.
  This signals "done recording, processing now."
- Same envelope style as start sound

**Delivery confirmation (optional, on text delivered):**
- A barely-audible soft "tick" — white noise burst at 0.05 amplitude for 20ms
- This is the "your text landed" signal

Generate these as numpy arrays and play via sounddevice. Cache them in memory on startup.

### 4D. SETTINGS WINDOW (OPTIONAL FOR V1 — LOW PRIORITY)

If built, it should be a single-window CustomTkinter app:

```
┌─ Koe Settings ──────────────────────────────────┐
│                                                   │
│  Hotkey               [Ctrl + Space      ]       │
│  Output mode          [● Type  ○ Clipboard]      │
│                                                   │
│  ── Transcription ──────────────────────────     │
│  Model                [base           ▾]         │
│  Language             [English        ▾]         │
│  Device               [CUDA (GPU)     ▾]         │
│                                                   │
│  ── Cleanup ────────────────────────────────     │
│  [✓] Remove filler words                         │
│  [✓] Fix punctuation                             │
│  [✓] Fix grammar                                 │
│                                                   │
│  ── Interface ──────────────────────────────     │
│  [✓] Show recording overlay                      │
│  [✓] Sound feedback                              │
│                                                   │
│  Config file: ~/.koe/config.toml  [Open]         │
│                                                   │
│                              [Save]  [Cancel]    │
│                                                   │
└──────────────────────────────────────────────────┘
```

- Dark theme (CustomTkinter dark mode)
- Accent color: coral (#ff4f3d)
- Keep it simple. One page. No tabs.
- For v1, just opening config.toml in Notepad is acceptable.

---

## 5. IMPLEMENTATION APPROACH

### Technology Decisions

**Overlay window:** Use `tkinter` with `overrideredirect(True)` for the frameless window.
For the waveform animation, use a `tkinter.Canvas` widget with `after()` scheduling for
60fps updates. To make it click-through and translucent on Windows:

```python
import ctypes
hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
# Set layered + transparent (click-through)
ctypes.windll.user32.SetWindowLongW(hwnd, -20,
    ctypes.windll.user32.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20)
# Set transparency
ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, int(255 * 0.9), 0x02)
```

**Waveform rendering:** The overlay's Canvas should draw ~50 rounded rectangles per frame.
Get audio RMS from the recording buffer in real-time. Use a ring buffer of the last ~50
RMS values to drive the 50 bars. Interpolate each bar's height smoothly:

```python
# Smooth interpolation for each bar
current_height = current_height + (target_height - current_height) * 0.3
```

**Sound generation:**
```python
import numpy as np
import sounddevice as sd

def make_blip(freq=880, duration=0.08, volume=0.15, sample_rate=44100):
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # Exponential decay envelope
    envelope = np.exp(-t * 40)
    # Sine wave with envelope
    signal = volume * np.sin(2 * np.pi * freq * t) * envelope
    return signal.astype(np.float32)

START_SOUND = make_blip(880, 0.08, 0.15)
STOP_SOUND = np.concatenate([make_blip(660, 0.04, 0.12), make_blip(440, 0.06, 0.12)])

def play_sound(sound):
    sd.play(sound, samplerate=44100, blocking=False)
```

**System tray:** Use `pystray` with PIL-generated icons. Generate the waveform icon
programmatically:

```python
from PIL import Image, ImageDraw

def create_tray_icon(state="idle"):
    colors = {"idle": "#ff4f3d", "recording": "#ff6b5a", "processing": "#ffb347", "error": "#666"}
    color = colors.get(state, colors["idle"])

    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw 3 bars (like a mini waveform)
    bar_width = 5
    gap = 3
    heights = [12, 20, 14]
    start_x = 6
    for i, h in enumerate(heights):
        x = start_x + i * (bar_width + gap)
        y = 16 - h // 2
        draw.rounded_rectangle([x, y, x + bar_width, y + h], radius=2, fill=color)

    return img
```

### File Structure (after UI work)

```
koe/
├── __init__.py
├── __main__.py
├── app.py           # Main orchestrator (UPDATE: wire in new overlay + sounds)
├── config.py        # Config (no changes needed)
├── audio.py         # Audio recording (ADD: real-time RMS callback for waveform)
├── transcriber.py   # Whisper STT (no changes needed)
├── cleaner.py       # Text cleanup (no changes needed)
├── output.py        # Output engine (no changes needed)
├── hotkey.py        # Hotkey listener (no changes needed)
├── overlay.py       # REWRITE: Premium recording overlay with waveform
├── sounds.py        # NEW: Sound generation and playback
├── icons.py         # NEW: Tray icon generation for all states
└── assets/          # (empty — everything is generated programmatically)
```

### Key Modifications to Existing Code

**audio.py — Add real-time RMS for waveform:**
The `_audio_callback` method already receives audio chunks. Add a thread-safe RMS
value that the overlay can read:

```python
# In AudioRecorder.__init__:
self._current_rms = 0.0

# In _audio_callback:
if self._recording:
    with self._lock:
        self._chunks.append(indata[:, 0].copy())
    # Update RMS for waveform visualization (no lock needed, atomic float write)
    self._current_rms = float(np.sqrt(np.mean(indata ** 2)))

@property
def current_rms(self) -> float:
    return self._current_rms
```

**app.py — Wire new overlay and sounds:**
Replace the old overlay.py usage with the new premium overlay. Add sound playback
on record start/stop. Pass the recorder's `current_rms` property to the overlay
for real-time waveform updates.

---

## 6. WHAT "DONE" LOOKS LIKE

When Koe is running:

1. **Idle:** Nothing visible except a small coral waveform icon in the system tray.
   Hovering shows "Koe — Hold Ctrl+Space to speak."

2. **User presses Ctrl+Space:** A soft blip plays. A dark translucent pill slides up
   from the bottom-right corner with a fade-in. Inside, coral bars dance to the
   user's voice in real-time. A small red dot pulses. A timer ticks up.

3. **User releases Ctrl+Space:** A descending two-tone plays. The waveform bars freeze.
   An amber shimmer sweeps across them. "Processing..." appears. The tray icon turns amber.

4. **Text delivered:** A barely-audible tick. The overlay slides down and fades out.
   The tray icon returns to coral. The transcribed, cleaned text appears wherever the
   user's cursor was — either typed character by character or pasted from clipboard.

5. **The whole cycle feels instant, satisfying, and invisible.** The user forgets
   the tool exists between uses. That's the goal.

---

## 7. ANTI-PATTERNS TO AVOID

- **No electron. No web views. No browser.** This is a native Python app.
- **No AI slop in the UI.** No gradient meshes. No glassmorphism trends. No "frosted
  glass" that looks like every other 2024 app. The aesthetic is WARM + DARK + MINIMAL.
- **No feature creep.** V1 does ONE thing: hold-to-talk voice-to-text. No meeting notes.
  No PDF merging. No "AI assistant mode." That stuff comes later. Nail the core first.
- **No settings complexity.** The app should work perfectly with zero configuration.
  Settings exist for power users who want to tweak, not as a requirement.
- **No notifications or popups.** Ever. The overlay is the only visual element beyond
  the tray icon.
- **No "loading" or "downloading model" screens.** If the model isn't ready, just
  don't respond to the hotkey. Log it. The user will try again in a few seconds.

---

## 8. TESTING CHECKLIST

After building, verify:

- [ ] Tray icon appears on launch with coral waveform bars
- [ ] Right-click menu shows mode toggle, model selection, settings, quit
- [ ] Ctrl+Space triggers recording (check with logging)
- [ ] Start sound plays on key press (subtle, not jarring)
- [ ] Overlay appears bottom-right with waveform animation
- [ ] Waveform responds to actual audio input (speak = big bars, silence = small bars)
- [ ] Timer increments while recording
- [ ] Releasing Ctrl+Space plays stop sound
- [ ] Overlay transitions to processing state (amber, shimmer, "Processing...")
- [ ] Tray icon changes to amber during processing
- [ ] Text appears in a focused text field (open Notepad, focus it, then dictate)
- [ ] Overlay fades out after delivery
- [ ] Tray icon returns to coral
- [ ] Accidental taps (<300ms) don't trigger anything visible
- [ ] Overlay is click-through (click through it to interact with apps behind it)
- [ ] App quits cleanly from tray menu
- [ ] Config.toml is created on first run at ~/.koe/config.toml
- [ ] Changing model in config.toml and restarting uses the new model

---

## 9. DEPENDENCIES

```
# Core
faster-whisper>=1.0.0
sounddevice>=0.4.6
numpy>=1.24.0
pystray>=0.19.0
Pillow>=10.0.0
keyboard>=0.13.5
pyperclip>=1.8.2
pywin32>=306
tomli>=2.0.0          # Python <3.11 only
tomli-w>=1.0.0

# Optional for settings UI
customtkinter>=5.2.0
```

---

## 10. REFERENCE: EXISTING CODEBASE

The following modules already exist and work. Do NOT rewrite them unless specified:

- `config.py` — TOML config with dataclass schemas. Works. Don't touch.
- `audio.py` — Mic recording. ADD the `current_rms` property as described above.
- `transcriber.py` — Whisper STT. Works. Don't touch.
- `cleaner.py` — Rule-based text cleanup. Works. Don't touch.
- `output.py` — Win32 keystroke injection + clipboard. Works. Don't touch.
- `hotkey.py` — Global Ctrl+Space detection. Works. Don't touch.
- `__main__.py` — Entry point. Works. Don't touch.

**Modules to REWRITE or CREATE:**
- `overlay.py` — REWRITE completely per Section 4B specs
- `sounds.py` — CREATE per Section 4C specs
- `icons.py` — CREATE per Section 4A specs
- `app.py` — UPDATE to wire new overlay, sounds, and icons together
