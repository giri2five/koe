"""Output module for Koe.

Delivers transcribed text to the user via:
1. Keystroke injection - simulates typing into the focused text field
2. Clipboard paste - copies to clipboard and simulates Ctrl+V

Uses win32 APIs for reliable keystroke simulation on Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from enum import Enum

import keyboard
import pyperclip

from koe.config import OutputConfig

logger = logging.getLogger(__name__)


class OutputMode(Enum):
    BOTH = "both"
    TYPE = "type"
    CLIPBOARD = "clipboard"


@dataclass
class DeliveryResult:
    """Outcome of a delivery attempt."""

    copied: bool = False
    pasted: bool = False
    typed: bool = False
    delivered: bool = False
    reason: str = ""


@dataclass
class WindowTarget:
    """The app that should receive dictated text."""

    hwnd: int
    pid: int | None = None
    exe: str | None = None    # basename of the process image (e.g. "chrome.exe")
    title: str | None = None  # window title at capture time


class OutputEngine:
    """Delivers text to the focused application."""

    def __init__(self, config: OutputConfig):
        self.config = config
        self._mode = OutputMode(config.default_mode)

    @property
    def mode(self) -> OutputMode:
        return self._mode

    @staticmethod
    def get_foreground_window() -> WindowTarget | None:
        """Return the current foreground window handle and process id."""
        try:
            import ctypes
            import os as _os

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(user32.GetForegroundWindow())
            if not hwnd:
                return None

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid_val = int(pid.value) or None

            # Resolve exe basename
            exe: str | None = None
            if pid_val:
                try:
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid_val)
                    if handle:
                        try:
                            size = ctypes.c_ulong(1024)
                            buf = ctypes.create_unicode_buffer(size.value)
                            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                                exe = _os.path.basename(buf.value)
                        finally:
                            kernel32.CloseHandle(handle)
                except Exception:
                    pass

            # Resolve window title
            title: str | None = None
            try:
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    tbuf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, tbuf, length + 1)
                    title = tbuf.value or None
            except Exception:
                pass

            return WindowTarget(hwnd=hwnd, pid=pid_val, exe=exe, title=title)
        except Exception:
            return None

    def toggle_mode(self):
        """Switch between the two explicit write modes."""
        if self._mode == OutputMode.TYPE:
            self._mode = OutputMode.BOTH
        else:
            self._mode = OutputMode.TYPE
        logger.info("Output mode: %s", self._mode.value)
        return self._mode

    def deliver(self, text: str, target_hwnd: WindowTarget | None = None) -> DeliveryResult:
        """Send text to the focused application."""
        if not text:
            return DeliveryResult(reason="empty")

        if self._mode == OutputMode.BOTH:
            return self.copy_and_type(text, target_hwnd)
        if self._mode == OutputMode.TYPE:
            return self.type_text(text, target_hwnd)
        return self.paste_from_clipboard(text, target_hwnd)

    def copy_and_type(self, text: str, target_hwnd: WindowTarget | None = None) -> DeliveryResult:
        """Copy text first, then paste into the target app, with typing as fallback."""
        result = DeliveryResult()
        if not self._copy_text(text):
            result.reason = "copy_failed"
            return result

        result.copied = True
        self._wait_for_modifiers_release()
        self._release_modifier_keys()
        time.sleep(0.12)   # give app time to process hotkey-up before Ctrl+V

        self._log_focus_change("both mode", target_hwnd)

        if self._paste_clipboard():
            result.pasted = True
            result.delivered = True
            result.reason = "copied_and_pasted"
            return result

        logger.warning("Paste failed in both mode; falling back to type injection")
        if self._type_text(text, target_hwnd):
            result.typed = True
            result.delivered = True
            result.reason = "copied_and_typed"
            return result

        result.reason = "write_failed"
        return result

    def type_text(self, text: str, target_hwnd: WindowTarget | None = None) -> DeliveryResult:
        """Type directly and fall back to the clipboard path on failure."""
        if self._type_text(text, target_hwnd):
            return DeliveryResult(typed=True, delivered=True, reason="typed")

        logger.warning("Type injection failed; falling back to clipboard paste")
        fallback = self.paste_from_clipboard(text, target_hwnd)
        if fallback.delivered:
            fallback.reason = "clipboard_fallback"
        return fallback

    def copy_only(self, text: str) -> DeliveryResult:
        """Copy text to the clipboard without pasting it."""
        if self._copy_text(text):
            return DeliveryResult(copied=True, delivered=False, reason="copied")
        return DeliveryResult(reason="copy_failed")

    def paste_from_clipboard(self, text: str, target_hwnd: WindowTarget | None = None) -> DeliveryResult:
        """Copy text, then paste when the same target still owns focus."""
        result = DeliveryResult()
        if not self._copy_text(text):
            result.reason = "copy_failed"
            return result

        result.copied = True
        self._wait_for_modifiers_release()
        self._release_modifier_keys()
        time.sleep(0.12)   # give app time to process hotkey-up before Ctrl+V
        self._log_focus_change("clipboard mode", target_hwnd)

        if self._paste_clipboard():
            result.pasted = True
            result.delivered = True
            result.reason = "pasted"
            return result

        if self._type_text(text, target_hwnd):
            result.typed = True
            result.delivered = True
            result.reason = "typed_fallback"
            logger.warning("Clipboard paste failed; fell back to type injection")
            return result

        result.reason = "paste_failed"
        return result

    def _type_text(self, text: str, target_hwnd: WindowTarget | None = None) -> bool:
        """Type text into the focused field using win32 SendInput."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            INPUT_KEYBOARD = 1
            KEYEVENTF_UNICODE = 0x0004
            KEYEVENTF_KEYUP = 0x0002

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t),
                ]

            class INPUT(ctypes.Structure):
                class _INPUT(ctypes.Union):
                    _fields_ = [
                        ("ki", KEYBDINPUT),
                        ("_pad", ctypes.c_byte * 32),  # match MOUSEINPUT size on 64-bit
                    ]
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("_input", _INPUT),
                ]

            self._log_focus_change("type injection", target_hwnd)

            self._wait_for_modifiers_release()
            self._release_modifier_keys()
            time.sleep(0.03)

            def _send_char(char: str) -> bool:
                inputs = (INPUT * 2)()

                inputs[0].type = INPUT_KEYBOARD
                inputs[0]._input.ki.wVk = 0
                inputs[0]._input.ki.wScan = ord(char)
                inputs[0]._input.ki.dwFlags = KEYEVENTF_UNICODE

                inputs[1].type = INPUT_KEYBOARD
                inputs[1]._input.ki.wVk = 0
                inputs[1]._input.ki.wScan = ord(char)
                inputs[1]._input.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP

                sent = user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
                return sent == 2

            for char in text:
                scan_char = "\r" if char == "\n" else char
                if not _send_char(scan_char):
                    logger.warning("SendInput returned a short write while typing")
                    return False

                if self.config.typing_speed > 0:
                    time.sleep(self.config.typing_speed / 1000.0)

            logger.info("Typed %s chars into focused field", len(text))
            return True

        except Exception as exc:
            logger.error("Type injection failed: %s", exc)
            return self._keyboard_type_fallback(text)

    def _copy_text(self, text: str) -> bool:
        """Copy text to the system clipboard."""
        try:
            pyperclip.copy(text)
            logger.info("Copied %s chars to clipboard", len(text))
            return True
        except Exception as exc:
            logger.error("Clipboard copy failed: %s", exc)
            return False

    def _paste_clipboard(self) -> bool:
        """Simulate Ctrl+V."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            VK_CONTROL = 0x11
            VK_V = 0x56
            INPUT_KEYBOARD = 1
            KEYEVENTF_KEYUP = 0x0002

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t),
                ]

            class INPUT(ctypes.Structure):
                class _INPUT(ctypes.Union):
                    # Pad to 32 bytes so the union matches MOUSEINPUT's size
                    # on 64-bit Windows — without this ctypes.sizeof(INPUT)
                    # is ~28 instead of 40 and SendInput returns 0.
                    _fields_ = [
                        ("ki", KEYBDINPUT),
                        ("_pad", ctypes.c_byte * 32),
                    ]
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("_input", _INPUT),
                ]

            inputs = (INPUT * 4)()

            inputs[0].type = INPUT_KEYBOARD
            inputs[0]._input.ki.wVk = VK_CONTROL

            inputs[1].type = INPUT_KEYBOARD
            inputs[1]._input.ki.wVk = VK_V

            inputs[2].type = INPUT_KEYBOARD
            inputs[2]._input.ki.wVk = VK_V
            inputs[2]._input.ki.dwFlags = KEYEVENTF_KEYUP

            inputs[3].type = INPUT_KEYBOARD
            inputs[3]._input.ki.wVk = VK_CONTROL
            inputs[3]._input.ki.dwFlags = KEYEVENTF_KEYUP

            sent = user32.SendInput(4, inputs, ctypes.sizeof(INPUT))
            if sent != 4:
                logger.warning("SendInput pasted only %s/4 events", sent)
                return self._keyboard_paste_fallback()

            logger.info("Pasted from clipboard")
            return True

        except Exception as exc:
            logger.error("Clipboard paste failed: %s", exc)
            return self._keyboard_paste_fallback()

    @staticmethod
    def _wait_for_modifiers_release(timeout: float = 0.5):
        """Give the hotkey time to fully release before sending output."""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            deadline = time.monotonic() + timeout
            modifier_codes = (
                0x10, 0xA0, 0xA1,  # shift
                0x11, 0xA2, 0xA3,  # ctrl
                0x12, 0xA4, 0xA5,  # alt
                0x5B, 0x5C,        # windows
            )
            while time.monotonic() < deadline:
                any_down = any((user32.GetAsyncKeyState(code) & 0x8000) != 0 for code in modifier_codes)
                if not any_down:
                    return
                time.sleep(0.01)
        except Exception:
            time.sleep(0.05)

    @staticmethod
    def _keyboard_paste_fallback() -> bool:
        """Fallback paste path using the keyboard library."""
        try:
            OutputEngine._release_modifier_keys()
            time.sleep(0.03)
            keyboard.send("ctrl+v")
            logger.info("Pasted from clipboard via keyboard fallback")
            return True
        except Exception as exc:
            logger.error("Keyboard paste fallback failed: %s", exc)
            return False

    def _keyboard_type_fallback(self, text: str) -> bool:
        """Fallback typing path using the keyboard library."""
        try:
            self._release_modifier_keys()
            time.sleep(0.03)
            keyboard.write(text, delay=self.config.typing_speed / 1000.0 if self.config.typing_speed > 0 else 0)
            logger.info("Typed %s chars via keyboard fallback", len(text))
            return True
        except Exception as exc:
            logger.error("Keyboard type fallback failed: %s", exc)
            return False

    @staticmethod
    def _same_target(expected: WindowTarget, current: WindowTarget) -> bool:
        """Treat windows from the same process as the same target app."""
        if expected.hwnd == current.hwnd:
            return True
        if expected.pid is not None and current.pid is not None and expected.pid == current.pid:
            return True
        return False

    def _log_focus_change(self, context: str, target_hwnd: WindowTarget | None):
        """Log focus drift without blocking delivery."""
        if target_hwnd is None:
            return

        current = self.get_foreground_window()
        if current and not self._same_target(target_hwnd, current):
            logger.warning(
                "Focus changed before %s from %s/%s to %s/%s; delivering to current foreground window",
                context,
                target_hwnd.hwnd,
                target_hwnd.pid,
                current.hwnd,
                current.pid,
            )

    @staticmethod
    def _release_modifier_keys():
        """Release common modifier keys so hotkey state does not leak into output."""
        for key in ("ctrl", "alt", "shift", "windows"):
            try:
                keyboard.release(key)
            except Exception:
                pass
