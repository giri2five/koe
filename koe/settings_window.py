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

    def clear_history(self) -> dict:
        """Clear dictation history."""
        return self._owner.clear_history()

    def copy_text(self, text: str) -> dict:
        """Copy arbitrary text to clipboard (used by history entries)."""
        return self._owner.copy_text(text)

    def get_snippets_data(self) -> dict:
        """Return current snippets + suggestions for the Snippets page."""
        return self._owner.get_snippets_data()

    def add_snippet(self, trigger: str, expansion: str) -> dict:
        """Add or update a snippet."""
        return self._owner.add_snippet(trigger, expansion)

    def delete_snippet(self, trigger: str) -> dict:
        """Delete a snippet by trigger."""
        return self._owner.delete_snippet(trigger)

    def open_file_dialog(self) -> dict:
        """Open a native audio file picker. Returns {path, filename}."""
        return self._owner.open_file_dialog()

    def transcribe_file(self, path: str) -> dict:
        """Transcribe an audio file at the given path."""
        return self._owner.transcribe_file(path)


class SettingsWindow:
    """Normal desktop app window for Koe."""

    def __init__(
        self,
        on_save: Callable[[KoeConfig], None],
        get_runtime_state: Callable[[], dict],
        on_copy_last_result: Callable[[], dict],
        on_clear_last_result: Callable[[], dict],
        on_quit: Callable[[], None] | None = None,
        on_clear_history: Callable[[], dict] | None = None,
        on_get_snippets_data: Callable[[], dict] | None = None,
        on_add_snippet: Callable[[str, str], dict] | None = None,
        on_delete_snippet: Callable[[str], dict] | None = None,
        on_transcribe_file: Callable[[str], dict] | None = None,
    ):
        self._on_save = on_save
        self._get_runtime_state = get_runtime_state
        self._on_copy_last_result = on_copy_last_result
        self._on_clear_last_result = on_clear_last_result
        self._on_quit = on_quit
        self._on_clear_history = on_clear_history
        self._on_get_snippets_data = on_get_snippets_data
        self._on_add_snippet = on_add_snippet
        self._on_delete_snippet = on_delete_snippet
        self._on_transcribe_file = on_transcribe_file

        self._lock = threading.RLock()
        self._window: webview.Window | None = None
        self._bridge = _SettingsBridge(self)
        self._config: KoeConfig | None = None
        self._quit_requested = False
        self._loaded = threading.Event()
        self._ui_started = False
        self._show_requested = True
        self._is_hidden = True  # track whether window is currently hidden

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

        # Tell Windows to treat this process as "Koe", not "python.exe".
        # This gives Koe its own taskbar group and lets WM_SETICON stick.
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Koe.VoiceApp.1")
        except Exception:
            pass

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
        logger.info("show() called — window=%s loaded=%s", self._window is not None, self._loaded.is_set())
        if self._window is None:
            return
        if not self._loaded.is_set():
            # Page still loading — it will show itself via _on_loaded
            return
        try:
            # Only reposition if hidden — don't un-maximize an already-visible window
            if self._is_hidden:
                self._restore_geometry()
                self._window.show()
                self._is_hidden = False
            self._raise_to_front()
            logger.info("Koe window raised to front")
        except Exception:
            logger.exception("Failed to show Koe window")

    def hide(self):
        """Hide the app window while keeping Koe alive."""
        self._show_requested = False
        self._is_hidden = True
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
        # If the Qt event loop doesn't exit within 3 s (e.g. called from a
        # non-Qt thread while Qt is blocked), force the process out so the
        # single-instance mutex is released and restarts work cleanly.
        import threading, os
        def _force_exit():
            import time as _t
            _t.sleep(3.0)
            logger.warning("Koe shutdown timed out — forcing exit")
            os._exit(0)
        threading.Thread(target=_force_exit, daemon=True, name="koe-exit-watchdog").start()

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

    def clear_history(self) -> dict:
        """Clear dictation history through the app callback."""
        if self._on_clear_history is not None:
            return self._on_clear_history()
        return self.get_state()

    def copy_text(self, text: str) -> dict:
        """Copy arbitrary text to clipboard (used by history entries)."""
        import pyperclip
        try:
            pyperclip.copy(str(text))
        except Exception:
            pass
        return self.get_state()

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
            "history": runtime.get("history", []),
            "model": config.transcription.model,
            "snippetCount": runtime.get("snippetCount", 0),
            "snippetsPath": str(runtime.get("snippetsPath", "")),
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

    def get_snippets_data(self) -> dict:
        """Return snippets + suggestions for the Snippets page."""
        if self._on_get_snippets_data:
            return self._on_get_snippets_data()
        return {"snippets": [], "suggestions": []}

    def add_snippet(self, trigger: str, expansion: str) -> dict:
        """Add or update a snippet and return updated data."""
        if self._on_add_snippet:
            return self._on_add_snippet(trigger, expansion)
        return self.get_snippets_data()

    def delete_snippet(self, trigger: str) -> dict:
        """Delete a snippet and return updated data."""
        if self._on_delete_snippet:
            return self._on_delete_snippet(trigger)
        return self.get_snippets_data()

    def open_file_dialog(self) -> dict:
        """Open a native audio file picker and return {path, filename}."""
        if self._window is None:
            return {"path": "", "filename": ""}
        try:
            import webview
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("Audio files (*.mp3;*.wav;*.m4a;*.flac;*.ogg;*.aac;*.wma)",
                            "All files (*.*)"),
            )
            if result and result[0]:
                path = str(result[0])
                from pathlib import Path as _P
                return {"path": path, "filename": _P(path).name}
        except Exception:
            logger.exception("File dialog failed")
        return {"path": "", "filename": ""}

    def transcribe_file(self, path: str) -> dict:
        """Transcribe an audio file. Runs synchronously on the bridge thread."""
        if not path:
            return {"error": "No file selected"}
        if self._on_transcribe_file:
            return self._on_transcribe_file(path)
        return {"error": "Transcription not available"}

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
        logger.info("Koe UI loaded")
        self._loaded.set()
        self._restore_geometry()
        self._is_hidden = False
        threading.Thread(target=self._force_show_loop, daemon=True, name="koe-show").start()
        self._push_state()

    def _force_show_loop(self):
        """Show the Koe window via a subprocess (EnumWindows hangs inside the Qt process)."""
        import time, subprocess
        logger.info("force_show_loop: waiting for Qt to settle")
        time.sleep(1.0)
        # Let the subprocess find the HWND and call ShowWindow itself.
        ps = r"""
$sig = @'
using System; using System.Runtime.InteropServices; using System.Text;
public class W {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc f, IntPtr l);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int i);
    [DllImport("user32.dll")] public static extern int SetWindowLong(IntPtr h, int i, int v);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int w, int ht, uint f);
    public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
'@
Add-Type -TypeDefinition $sig
[W]::EnumWindows({param($h,$l)
    $s=New-Object System.Text.StringBuilder 256
    [W]::GetWindowText($h,$s,256)|Out-Null
    if($s.ToString() -eq 'Koe'){
        $r=New-Object W+RECT
        [W]::GetWindowRect($h,[ref]$r)|Out-Null
        if(($r.R-$r.L) -gt 400){
            # Remove WS_MAXIMIZEBOX (0x10000) from window style
            $style = [W]::GetWindowLong($h, -16)
            [W]::SetWindowLong($h, -16, $style -band (-bnot 0x10000)) | Out-Null
            # Refresh frame so the button disappears
            [W]::SetWindowPos($h, [IntPtr]::Zero, 0,0,0,0, 0x0037) | Out-Null
            [W]::ShowWindow($h,5)|Out-Null
            [W]::SetForegroundWindow($h)|Out-Null
        }
    }
    return $true
},[IntPtr]::Zero)|Out-Null
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                timeout=8, capture_output=True, text=True,
            )
            logger.info("force_show_loop: subprocess done (rc=%s)", result.returncode)
            if result.stderr:
                logger.warning("force_show_loop stderr: %s", result.stderr[:200])
        except Exception as exc:
            logger.error("force_show_loop subprocess failed: %s", exc)

    def _on_closing(self, window: webview.Window):
        with self._lock:
            quit_requested = self._quit_requested

        if quit_requested:
            return None

        try:
            self._is_hidden = True
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

    def _raise_to_front(self, hold_topmost_ms: int = 0):
        """Schedule a foreground-raise on a background thread after the window settles."""
        threading.Timer(0.35, self._do_raise_win32, args=(hold_topmost_ms,)).start()

    def _do_raise_win32(self, hold_topmost_ms: int = 0):
        """Win32 foreground-raise: restores, raises Z-order, and optionally holds topmost."""
        try:
            u32 = ctypes.windll.user32

            # Find the main Koe window (large window, not the tray tooltip at -32000,-32000)
            hwnd = self._find_main_hwnd(u32)
            if not hwnd:
                return

            # SW_SHOWNORMAL (1) shows the window for the first time (or after hide)
            # SW_RESTORE (9) un-minimizes if it was minimized — call both to cover all states
            u32.ShowWindow(hwnd, 1)
            u32.ShowWindow(hwnd, 9)

            # ctypes.c_void_p(-1/-2) produces correct 64-bit handle values on x64;
            # plain Python int -1 truncates to 32-bit 0xFFFFFFFF → error 1400.
            _HWND_TOPMOST   = ctypes.c_void_p(-1)
            _HWND_NOTOPMOST = ctypes.c_void_p(-2)
            _SWP_NOMOVE     = 0x0002
            _SWP_NOSIZE     = 0x0001
            flags = _SWP_NOMOVE | _SWP_NOSIZE

            u32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, flags)

            # Stamp our custom ICO onto the window so the taskbar shows it
            # instead of the generic python.exe icon.
            try:
                _LR_LOADFROMFILE = 0x0010
                _LR_DEFAULTSIZE  = 0x0040
                _IMAGE_ICON      = 1
                icon_path_w = str(self._icon_path)
                hicon = u32.LoadImageW(
                    None, icon_path_w, _IMAGE_ICON, 0, 0,
                    _LR_LOADFROMFILE | _LR_DEFAULTSIZE,
                )
                if hicon:
                    _WM_SETICON = 0x0080
                    u32.SendMessageW(hwnd, _WM_SETICON, 1, hicon)  # ICON_BIG
                    u32.SendMessageW(hwnd, _WM_SETICON, 0, hicon)  # ICON_SMALL
            except Exception:
                pass

            if hold_topmost_ms > 0:
                # Stay on top long enough for the user to see it, then release
                import time
                time.sleep(hold_topmost_ms / 1000.0)

            u32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            u32.SetForegroundWindow(hwnd)
        except Exception:
            logger.debug("Koe window raise skipped", exc_info=True)

    @staticmethod
    def _find_main_hwnd(u32) -> int:
        """Return the HWND for the main Koe window (skips tray tooltip at -32000,-32000)."""
        found = []

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_long)
        def _cb(hwnd, _lparam):
            buf = ctypes.create_unicode_buffer(64)
            u32.GetWindowTextW(hwnd, buf, 64)
            if buf.value == "Koe":
                rect = _RECT()
                u32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                # Main window is large; tray tooltip is tiny (160x28 at -32000,-32000)
                if w > 400 and h > 400:
                    found.append(hwnd)
                    return False  # stop enumeration
            return True

        u32.EnumWindows(_cb, 0)
        return found[0] if found else 0
