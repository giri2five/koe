# CODEX_TASKS.md — Task Breakdown for Codex

These are isolated, well-scoped tasks you can hand off to Codex one at a time. Each task has clear inputs, outputs, and acceptance criteria.

---

## Task 1: Sound Feedback

**Goal:** Play a subtle sound when recording starts and stops.

**Files to modify:** `koe/app.py`, `koe/assets/`

**Spec:**
- Add two short WAV files: `start.wav` (soft click/blip) and `stop.wav` (different tone)
- Generate them programmatically using numpy (sine wave blips, ~100ms each)
- Play them using `sounddevice.play()` in non-blocking mode
- Respect `config.ui.sound_feedback` toggle
- Do NOT use any external audio files or downloads

**Acceptance:** Running the app, the user hears a subtle blip when pressing and releasing Ctrl+Space.

---

## Task 2: Streaming Transcription Preview

**Goal:** Show a live text preview while the user is still speaking.

**Files to create:** `koe/streamer.py`
**Files to modify:** `koe/app.py`, `koe/overlay.py`

**Spec:**
- While recording, periodically (every ~2 seconds) take the current audio buffer and run a quick transcription
- Show the partial transcription in the overlay as a small floating text near the cursor
- When recording stops, do the final full transcription and replace the preview
- Use `transcriber.transcribe()` but on partial audio
- This is optional / can be toggled off for performance

**Acceptance:** While holding Ctrl+Space and speaking, the user sees partial text appearing.

---

## Task 3: Personal Dictionary

**Goal:** Let users define custom words/spellings that Whisper often gets wrong.

**Files to create:** `koe/dictionary.py`
**Files to modify:** `koe/cleaner.py`, `koe/config.py`

**Spec:**
- Add a `dictionary.txt` file in `~/.koe/` with one entry per line: `wrong_word -> correct_word`
- After transcription and cleanup, apply dictionary replacements
- Support regex patterns for flexible matching
- Example entries:
  ```
  kelp dao -> KelpDAO
  kernel dao -> KernelDAO
  defi -> DeFi
  eth -> ETH
  ```

**Acceptance:** Custom words are correctly replaced in the output.

---

## Task 4: Whisper Model Auto-Selection

**Goal:** Automatically pick the best Whisper model based on available GPU VRAM.

**Files to modify:** `koe/transcriber.py`, `koe/config.py`

**Spec:**
- On first run (or when config.transcription.model = "auto"), detect available VRAM
- Pick the largest model that fits:
  - <2GB VRAM → tiny
  - 2-4GB → base
  - 4-6GB → small
  - 6-8GB → medium
  - 8GB+ → large-v3
- Log the selection
- If no GPU, default to base on CPU

**Acceptance:** Running with model="auto" selects an appropriate model and logs why.

---

## Task 5: Multi-Language Support

**Goal:** Support multiple languages and auto-detection.

**Files to modify:** `koe/transcriber.py`, `koe/config.py`

**Spec:**
- When `config.transcription.language = "auto"`, let Whisper detect the language
- Log the detected language and confidence
- Support a `preferred_languages` list in config for faster detection
- Add a tray menu item showing current language

**Acceptance:** Speaking in different languages produces correct transcriptions.

---

## Task 6: Windows Installer

**Goal:** Create a one-click installer using PyInstaller or similar.

**Files to create:** `build.py` or `koe.spec`

**Spec:**
- Bundle everything into a single .exe or installer
- Include the Whisper model (base) in the bundle
- Create a Start Menu shortcut
- Create a "Run at startup" option
- Sign with a self-signed certificate (instructions in README)

**Acceptance:** Download .exe → run → Koe works. No Python installation needed.

---

## Task 7: Tray Icon States

**Goal:** Change the tray icon to reflect current state.

**Files to modify:** `koe/app.py`

**Spec:**
- Default state: neutral icon (current)
- Recording: icon turns red / has red dot
- Processing: icon turns orange / has spinner
- Error: icon turns grey with X
- Use `pystray.Icon.icon` property to swap images
- Create icons programmatically with PIL (no external assets)

**Acceptance:** Tray icon visually changes during recording and processing.
