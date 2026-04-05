"""Koe application - the main orchestrator."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np
import pyperclip

from koe import icons
from koe import sounds
from koe.audio import AudioRecorder
from koe.cleaner import TextCleaner
from koe.config import KoeConfig, load_config, save_config
from koe.devices import describe_selection
from koe.hotkey import HotkeyListener
from koe.output import OutputEngine, OutputMode, WindowTarget
from koe.overlay import Overlay, OverlayState
from koe.settings_window import SettingsWindow
from koe.transcriber import Transcriber

logger = logging.getLogger(__name__)


class KoeApp:
    """Main tray application for Koe."""

    def __init__(self, config: Optional[KoeConfig] = None):
        self.config = config or load_config()
        self._running = False
        self._tray_icon = None
        self._status_text = "Ready"
        self._target_window: WindowTarget | None = None
        self._last_transcript = ""
        self._last_cleaned = ""
        self._last_delivery = ""
        self._last_duration = ""
        self._history: list[dict] = []  # last 20 dictations

        self.recorder = AudioRecorder(self.config.audio)
        self.transcriber = Transcriber(self.config.transcription)
        self.cleaner = TextCleaner(self.config.cleanup)
        self.output = OutputEngine(self.config.output)
        sounds.set_output_device(self.config.audio.output_device)

        self.overlay = Overlay(
            self.config.ui.overlay_position,
            hotkey_hint=self._format_hotkey_hint(self.config.hotkey.trigger),
        )
        self.overlay.rms_source = lambda: self.recorder.current_rms

        self.hotkey = HotkeyListener(
            config=self.config.hotkey,
            on_record_start=self._on_record_start,
            on_record_stop=self._on_record_stop,
            on_mode_toggle=self._on_mode_toggle,
        )

        self._processing_lock = threading.Lock()
        self._settings_window = SettingsWindow(
            self._apply_settings,
            self._get_runtime_state,
            self._copy_last_result,
            self._clear_last_result,
            self._quit_from_popup,
            self._clear_history,
        )

    def _safe_set_overlay_state(self, state: OverlayState):
        """Update the overlay only when the feature is enabled."""
        if self.config.ui.show_overlay:
            self.overlay.set_state(state)

    def run(self):
        """Start Koe and block inside the desktop shell loop."""
        self._running = True
        logger.info("Starting Koe...")

        threading.Thread(target=self._preload_model, daemon=True).start()

        if self.config.ui.show_overlay:
            self.overlay.start()

        self.hotkey.start()
        self._run_tray()
        try:
            self._settings_window.run(self.config)
        except Exception:
            logger.exception("Desktop shell failed to start; continuing with tray runtime")
            while self._running:
                time.sleep(0.2)
        finally:
            if self._running:
                self._shutdown()

    def _preload_model(self):
        """Load the Whisper model so the first dictation is fast."""
        try:
            logger.info("Pre-loading Whisper model...")
            self.transcriber._ensure_model()
            logger.info("Model ready.")
        except Exception as exc:
            logger.error("Failed to pre-load model: %s", exc)

    def _on_record_start(self):
        """Called when the user presses the configured record hotkey."""
        if self.recorder.is_recording:
            return

        if self.config.ui.sound_feedback:
            sounds.play_start()

        try:
            self._set_status("Listening")
            self._target_window = self.output.get_foreground_window()
            self.recorder.start()
        except Exception as exc:
            logger.error("Recording start failed: %s", exc, exc_info=True)
            self._set_status("Mic error")
            self._target_window = None
            self._update_tray_icon("error")
            return

        self._safe_set_overlay_state(OverlayState.RECORDING)
        self._update_tray_icon("recording")

    def _on_record_stop(self):
        """Called when the user releases the configured record hotkey."""
        if not self.recorder.is_recording:
            return

        if self.config.ui.sound_feedback:
            sounds.play_stop()

        audio = self.recorder.stop()
        if audio is None:
            self._set_status("Ready")
            self._safe_set_overlay_state(OverlayState.HIDDEN)
            self._update_tray_icon("idle")
            self._target_window = None
            return

        self._last_duration = f"{len(audio) / self.config.audio.sample_rate:.2f}s"

        threading.Thread(target=self._process_audio, args=(audio,), daemon=True).start()

    def _process_audio(self, audio: np.ndarray):
        """Transcribe, clean, and deliver text."""
        if not self._processing_lock.acquire(blocking=False):
            logger.warning("Already processing, skipping")
            return

        try:
            # Hard silence gate: if audio energy is basically nothing, skip transcription
            # entirely to prevent Whisper hallucinations ("thank you very much", etc.)
            rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
            if rms < 0.006:
                logger.info("Audio RMS %.5f below silence gate — skipping transcription", rms)
                self._last_transcript = ""
                self._last_cleaned = ""
                self._last_delivery = "No speech heard"
                self._set_status("No speech heard")
                self._safe_set_overlay_state(OverlayState.HIDDEN)
                self._update_tray_icon("idle")
                return

            self._set_status("Processing")
            self._safe_set_overlay_state(OverlayState.PROCESSING)
            self._update_tray_icon("processing")

            text = self.transcriber.transcribe(audio)
            if not text:
                logger.info("No text transcribed")
                self._last_transcript = ""
                self._last_cleaned = ""
                self._last_delivery = "No speech heard"
                self._set_status("No speech heard")
                return

            self._last_transcript = text
            text = self.cleaner.clean(text)
            if not text:
                self._last_cleaned = ""
                self._last_delivery = "Nothing to send"
                self._set_status("Nothing to send")
                return

            self._last_cleaned = text
            delivery = self.output.deliver(text, self._target_window)

            if self.config.ui.sound_feedback and delivery.delivered:
                sounds.play_deliver()

            if delivery.delivered:
                self._set_status("Written and copied" if delivery.copied else "Typed")
                self._last_delivery = "Written into app and copied"
            elif delivery.copied:
                self._set_status("Copied only")
                self._last_delivery = "Copied only"
            else:
                self._set_status("Write failed")
                self._update_tray_icon("error")
                self._last_delivery = "Write failed"

            logger.info(
                "Delivery result: reason=%s copied=%s pasted=%s typed=%s delivered=%s text='%s'",
                delivery.reason,
                delivery.copied,
                delivery.pasted,
                delivery.typed,
                delivery.delivered,
                text[:80],
            )
            if delivery.delivered:
                from datetime import datetime as _dt
                self._history.append({"text": text, "time": _dt.now().strftime("%H:%M")})
                if len(self._history) > 20:
                    self._history = self._history[-20:]

        except Exception as exc:
            logger.error("Processing failed: %s", exc, exc_info=True)
            self._last_delivery = "Processing error"
            self._set_status("Error")
            self._update_tray_icon("error")
            time.sleep(1.5)

        finally:
            self._safe_set_overlay_state(OverlayState.HIDDEN)
            self._target_window = None
            if self._status_text not in {
                "Written and copied",
                "Typed",
                "Copied only",
                "No speech heard",
                "Nothing to send",
                "Write failed",
                "Error",
                "Mic error",
            }:
                self._set_status("Ready")
            if self._status_text in {"Write failed", "Error", "Mic error"}:
                self._update_tray_icon("error")
            else:
                self._update_tray_icon("idle")
            self._processing_lock.release()

    def _on_mode_toggle(self):
        """Toggle between type and clipboard mode."""
        mode = self.output.toggle_mode()
        self.config.output.default_mode = mode.value
        save_config(self.config)
        self._settings_window.sync_config(self.config)
        logger.info("Output mode: %s", mode.value)

    def _run_tray(self):
        """Run the system tray icon."""
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Koe", None, enabled=False),
            pystray.MenuItem("Open Koe", self._open_config, default=True),
            pystray.MenuItem(lambda item: f"Status: {self._status_text}", None, enabled=False),
            pystray.MenuItem(
                lambda item: f"Mic: {describe_selection(self.config.audio.device, 'input')}",
                None,
                enabled=False,
            ),
            pystray.MenuItem(
                lambda item: f"Audio: {describe_selection(self.config.audio.output_device, 'output')}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show Window", self._open_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Koe", self._on_quit),
        )

        self._tray_icon = pystray.Icon(
            name="Koe",
            icon=icons.get_icon("idle"),
            title=f"Koe - Hold {self._format_hotkey_hint(self.config.hotkey.trigger)} to speak",
            menu=menu,
        )

        logger.info("Koe is running. Hold %s to speak.", self._format_hotkey_hint(self.config.hotkey.trigger))
        self._tray_icon.run_detached()

    def _update_tray_icon(self, state: str):
        """Update tray icon state."""
        if self._tray_icon is None:
            return
        try:
            self._tray_icon.icon = icons.get_icon(state)
            self._tray_icon.title = f"Koe - {self._status_text}"
            self._tray_icon.update_menu()
        except Exception:
            pass

    def _open_config(self, icon=None, item=None):
        """Open the main Koe desktop window."""
        self._settings_window.show(self.config)

    def _apply_settings(self, new_config: KoeConfig):
        """Apply settings saved from the popup."""
        self.config = new_config
        save_config(self.config)

        self.recorder.config = self.config.audio
        self.recorder._sample_rate = self.config.audio.sample_rate

        self.transcriber.config = self.config.transcription
        self.transcriber.unload()

        self.cleaner.config = self.config.cleanup

        self.output.config = self.config.output
        self.output._mode = OutputMode(self.config.output.default_mode)

        sounds.set_output_device(self.config.audio.output_device)

        self.overlay._position = self.config.ui.overlay_position
        self.overlay._hotkey_hint = self._format_hotkey_hint(self.config.hotkey.trigger)
        if self.config.ui.show_overlay:
            self._safe_set_overlay_state(OverlayState.HIDDEN)
        else:
            self.overlay.set_state(OverlayState.HIDDEN)

        logger.info(
            "Settings updated: input=%s output=%s mode=%s model=%s runtime=%s",
            self.config.audio.device,
            self.config.audio.output_device,
            self.config.output.default_mode,
            self.config.transcription.model,
            self.config.transcription.device,
        )
        self._settings_window.sync_config(self.config)
        self._update_tray_icon("idle")

    def _get_runtime_state(self) -> dict:
        """Return live runtime state for the desktop shell."""
        return {
            "status": self._status_text,
            "lastTranscript": self._last_transcript,
            "lastCleaned": self._last_cleaned,
            "lastDelivery": self._last_delivery,
            "lastDuration": self._last_duration,
            "history": list(self._history),
        }

    def _copy_last_result(self) -> dict:
        """Copy the latest useful text into the clipboard."""
        text = self._last_cleaned or self._last_transcript
        if text:
            pyperclip.copy(text)
            self._last_delivery = "Copied latest result"
            self._set_status("Copied latest result")
        return self._get_runtime_state()

    def _clear_last_result(self) -> dict:
        """Clear the most recent capture state shown in the app window."""
        self._last_transcript = ""
        self._last_cleaned = ""
        self._last_delivery = "Cleared"
        self._last_duration = ""
        self._set_status("Ready")
        return self._get_runtime_state()

    def _clear_history(self) -> dict:
        """Clear dictation history."""
        self._history.clear()
        return self._get_runtime_state()

    def _on_quit(self, icon, item):
        """Quit from the tray menu."""
        self._shutdown()
        icon.stop()

    def _quit_from_popup(self):
        """Quit requested from the popup footer."""
        self._shutdown()
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass

    def _shutdown(self):
        """Clean shutdown of all modules."""
        logger.info("Shutting down Koe...")
        self._running = False
        self.hotkey.stop()
        self._settings_window.shutdown()
        self.overlay.stop()
        self.transcriber.unload()
        self.cleaner.unload_llm()
        logger.info("Goodbye.")

    def _set_status(self, status: str):
        """Update runtime status for tray and desktop shell."""
        self._status_text = status
        self._settings_window.update_status()

    @staticmethod
    def _format_hotkey_hint(hotkey: str) -> str:
        """Render config hotkeys in compact UI form."""
        return " + ".join(part.strip().upper() for part in hotkey.split("+"))
