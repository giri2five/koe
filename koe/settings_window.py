"""Main desktop window for Koe, rendered with pywebview."""

from __future__ import annotations

import copy
import ctypes
import logging
import threading
import tempfile
import uuid
from pathlib import Path
from typing import Callable

import webview

from koe.config import KoeConfig
from koe.devices import DeviceOption, list_device_options
from koe.icons import ensure_icon_file
from koe.output import OutputMode

logger = logging.getLogger(__name__)


class _SettingsBridge:
    """JavaScript bridge for the Koe desktop shell."""

    def __init__(self, owner: "SettingsWindow"):
        self._owner = owner

    def get_state(self) -> dict:
        """Return the full runtime snapshot consumed by the web app shell."""
        return self._owner.get_state()

    def set_input_device(self, value: str) -> dict:
        """Select an input device and persist the updated config."""
        return self._owner.set_input_device(value)

    def set_output_mode(self, value: str) -> dict:
        """Select an output mode and persist the updated config."""
        return self._owner.set_output_mode(value)

    def set_overlay_enabled(self, enabled: bool) -> dict:
        """Toggle the live overlay setting."""
        return self._owner.set_overlay_enabled(enabled)

    def set_sound_enabled(self, enabled: bool) -> dict:
        """Toggle sound feedback."""
        return self._owner.set_sound_enabled(enabled)

    def hide_window(self) -> dict:
        """Hide the app window but keep Koe running in the background."""
        self._owner.hide()
        return self._owner.get_state()

    def copy_last_result(self) -> dict:
        """Copy the latest cleaned result."""
        return self._owner.copy_last_result()

    def clear_last_result(self) -> dict:
        """Clear the latest runtime result."""
        return self._owner.clear_last_result()

    def quit_app(self) -> None:
        """Quit Koe from the web UI."""
        self._owner.request_quit()


class SettingsWindow:
    """Normal desktop app window for Koe."""

    def __init__(
        self,
        on_save: Callable[[KoeConfig], None],
        get_runtime_state: Callable[[], dict],
        on_copy_last_result: Callable[[], dict],
        on_clear_last_result: Callable[[], dict],
        on_quit: Callable[[], None] | None = None,
    ):
        self._on_save = on_save
        self._get_runtime_state = get_runtime_state
        self._on_copy_last_result = on_copy_last_result
        self._on_clear_last_result = on_clear_last_result
        self._on_quit = on_quit

        self._lock = threading.RLock()
        self._window: webview.Window | None = None
        self._bridge = _SettingsBridge(self)
        self._config: KoeConfig | None = None
        self._quit_requested = False
        self._loaded = threading.Event()
        self._ui_started = False
        self._show_requested = True

        repo_root = Path(__file__).resolve().parents[1]
        self._index_path = repo_root / "ui-preview" / "index.html"
        self._icon_path = ensure_icon_file()
        self._storage_path = Path(tempfile.gettempdir()) / f"koe-webview-{uuid.uuid4().hex}"
        self._storage_path.mkdir(parents=True, exist_ok=True)

    def run(self, config: KoeConfig):
        """Create the desktop shell and enter the webview event loop."""
        with self._lock:
            self._config = copy.deepcopy(config)
            self._quit_requested = False
            self._loaded.clear()
            self._show_requested = True

        try:
            self._window = webview.create_window(
                "Koe",
                url=self._index_path.as_uri(),
                js_api=self._bridge,
                width=1280,
                height=820,
                min_size=(1024, 700),
                background_color="#050505",
                text_select=False,
                hidden=True,
            )
            self._window.events.closing += self._on_closing
            self._window.events.loaded += self._on_loaded
            self._ui_started = True

            webview.start(
                gui="qt",
                debug=False,
                private_mode=False,
                icon=str(self._icon_path),
                storage_path=str(self._storage_path),
            )
        except Exception:
            logger.exception("Failed to start Koe desktop shell")
            with self._lock:
                self._window = None
                self._ui_started = False
                self._loaded.clear()
            raise

    def show(self, config: KoeConfig | None = None):
        """Show the app window with the latest config snapshot."""
        if config is not None:
            self.sync_config(config)
        self._show_requested = True
        if self._window is None or not self._loaded.is_set():
            return
        try:
            self._restore_geometry()
            self._window.restore()
            self._window.show()
        except Exception:
            logger.exception("Failed to show Koe window")

    def hide(self):
        """Hide the app window while keeping Koe alive."""
        self._show_requested = False
        if self._window is not None:
            try:
                self._window.hide()
            except Exception:
                logger.exception("Failed to hide Koe window")

    def shutdown(self):
        """Destroy the webview window and exit the UI loop."""
        with self._lock:
            self._quit_requested = True
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                logger.exception("Failed to destroy Koe window")

    def request_quit(self):
        """Quit the whole app from a JS callback."""
        if self._on_quit is None:
            self.shutdown()
            return
        threading.Thread(target=self._on_quit, daemon=True, name="koe-ui-quit").start()

    def copy_last_result(self) -> dict:
        """Copy the latest cleaned result through the app callback."""
        return self._on_copy_last_result()

    def clear_last_result(self) -> dict:
        """Clear the latest runtime result through the app callback."""
        return self._on_clear_last_result()

    def sync_config(self, config: KoeConfig):
        """Update the web UI snapshot with the latest config."""
        with self._lock:
            self._config = copy.deepcopy(config)
        self._push_state()

    def update_status(self):
        """Push the latest runtime status into the web UI."""
        self._push_state()

    def get_state(self) -> dict:
        """Return the current UI state for the web shell."""
        with self._lock:
            config = copy.deepcopy(self._config) if self._config is not None else KoeConfig()
        runtime = dict(self._get_runtime_state() or {})
        status = str(runtime.get("status", "Ready"))

        input_options = list_device_options("input")
        output_options = [
            {"value": OutputMode.BOTH.value, "label": "Write into app and keep copied"},
            {"value": OutputMode.CLIPBOARD.value, "label": "Paste from clipboard"},
            {"value": OutputMode.TYPE.value, "label": "Type directly into app"},
        ]

        return {
            "status": status,
            "statusKey": self._status_key(status),
            "hotkey": self._format_hotkey(config.hotkey.trigger),
            "microphone": config.audio.device,
            "microphoneLabel": self._label_for_value(input_options, config.audio.device),
            "microphoneOptions": [
                {"value": option.value, "label": option.label} for option in input_options
            ],
            "outputMode": config.output.default_mode,
            "outputModeLabel": self._output_mode_label(config.output.default_mode),
            "outputOptions": output_options,
            "showOverlay": config.ui.show_overlay,
            "soundFeedback": config.ui.sound_feedback,
            "lastTranscript": str(runtime.get("lastTranscript", "")),
            "lastCleaned": str(runtime.get("lastCleaned", "")),
            "lastDelivery": str(runtime.get("lastDelivery", "")),
            "lastDuration": str(runtime.get("lastDuration", "")),
        }

    def set_input_device(self, value: str) -> dict:
        """Update the active microphone selection."""
        self._mutate_config(lambda config: setattr(config.audio, "device", value))
        return self.get_state()

    def set_output_mode(self, value: str) -> dict:
        """Update the output mode selection."""
        if value not in {OutputMode.BOTH.value, OutputMode.CLIPBOARD.value, OutputMode.TYPE.value}:
            return self.get_state()
        self._mutate_config(lambda config: setattr(config.output, "default_mode", value))
        return self.get_state()

    def set_overlay_enabled(self, enabled: bool) -> dict:
        """Persist the overlay visibility flag."""
        self._mutate_config(lambda config: setattr(config.ui, "show_overlay", bool(enabled)))
        return self.get_state()

    def set_sound_enabled(self, enabled: bool) -> dict:
        """Persist the sound feedback flag."""
        self._mutate_config(lambda config: setattr(config.ui, "sound_feedback", bool(enabled)))
        return self.get_state()

    def _mutate_config(self, mutation: Callable[[KoeConfig], None]):
        with self._lock:
            if self._config is None:
                self._config = KoeConfig()
            mutation(self._config)
            new_config = copy.deepcopy(self._config)

        self._on_save(new_config)
        self._push_state()

    def _push_state(self):
        if self._window is None or not self._loaded.is_set():
            return

        try:
            self._window.evaluate_js(
                f"window.__koeApplyState({self._json_dumps(self.get_state())});"
            )
        except Exception:
            logger.debug("Koe UI state push skipped", exc_info=True)

    def _on_loaded(self, window: webview.Window):
        self._loaded.set()
        if self._show_requested:
            self._restore_geometry()
            try:
                window.restore()
                window.show()
            except Exception:
                logger.debug("Initial Koe window restore skipped", exc_info=True)
        self._push_state()

    def _on_closing(self, window: webview.Window):
        with self._lock:
            quit_requested = self._quit_requested

        if quit_requested:
            return None

        try:
            window.hide()
        except Exception:
            logger.exception("Failed to hide Koe window on close")
        return False

    @staticmethod
    def _format_hotkey(hotkey: str) -> str:
        return " + ".join(part.strip().upper() for part in hotkey.split("+"))

    @staticmethod
    def _label_for_value(options: list[DeviceOption], value: str) -> str:
        for option in options:
            if option.value == value:
                return option.label
        return options[0].label if options else "No devices found"

    @staticmethod
    def _output_mode_label(value: str) -> str:
        if value == OutputMode.BOTH.value:
            return "Write into app and keep copied"
        if value == OutputMode.CLIPBOARD.value:
            return "Paste from clipboard"
        return "Type directly into app"

    @staticmethod
    def _status_key(status: str) -> str:
        lowered = status.lower()
        if "listen" in lowered:
            return "listening"
        if "process" in lowered:
            return "processing"
        if any(word in lowered for word in ("written", "typed", "copied", "delivered")):
            return "delivered"
        if any(word in lowered for word in ("route", "format")):
            return "structure"
        return "idle"

    @staticmethod
    def _json_dumps(payload: dict) -> str:
        import json

        return json.dumps(payload, ensure_ascii=False)

    def _restore_geometry(self):
        if self._window is None:
            return

        try:
            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            width = min(1260, max(1080, screen_w - 140))
            height = min(800, max(720, screen_h - 140))
            x = max((screen_w - width) // 2, 32)
            y = max((screen_h - height) // 2, 28)
            self._window.move(x, y)
            self._window.resize(width, height)
        except Exception:
            logger.debug("Koe window geometry restore skipped", exc_info=True)
