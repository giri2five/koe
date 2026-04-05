"""Global hotkey listener for Koe.

Detects hold-to-talk using the configured trigger key combination.
Uses the `keyboard` library for global hook on Windows.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Callable, Optional

import keyboard

from koe.config import HotkeyConfig

# ── Win32 virtual-key codes for generic modifier detection ─────────────────
# GetAsyncKeyState with these VKs checks EITHER side (left or right).
_VK_SHIFT   = 0x10   # VK_SHIFT   — left OR right Shift
_VK_CONTROL = 0x11   # VK_CONTROL — left OR right Ctrl
_VK_MENU    = 0x12   # VK_MENU    — left OR right Alt (including AltGr)
_VK_LWIN    = 0x5B   # VK_LWIN
_VK_RWIN    = 0x5C   # VK_RWIN

_MOD_VK = {
    "shift":   _VK_SHIFT,
    "ctrl":    _VK_CONTROL,
    "alt":     _VK_MENU,
    "windows": _VK_LWIN,
}


def _vk_pressed(vk: int) -> bool:
    """Return True if the virtual key is currently down (Win32 GetAsyncKeyState)."""
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _key_name_to_vk(name: str) -> int | None:
    """Map a key name to its Windows VK code, or None if unknown."""
    n = name.strip().lower()
    if len(n) == 1 and n.isalpha():
        return ord(n.upper())   # VK_A–VK_Z = 0x41–0x5A
    if len(n) == 1 and n.isdigit():
        return ord(n)           # VK_0–VK_9 = 0x30–0x39
    extras = {
        "space": 0x20, "enter": 0x0D, "return": 0x0D,
        "tab": 0x09, "backspace": 0x08, "esc": 0x1B, "escape": 0x1B,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
        "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
        "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    }
    return extras.get(n)

logger = logging.getLogger(__name__)


class HotkeyListener:
    """Listens for global hotkey events."""

    def __init__(
        self,
        config: HotkeyConfig,
        on_record_start: Callable,
        on_record_stop: Callable,
        on_mode_toggle: Callable,
        on_expand_snippet: Optional[Callable] = None,
    ):
        self.config = config
        self._on_record_start = on_record_start
        self._on_record_stop = on_record_stop
        self._on_mode_toggle = on_mode_toggle
        self._on_expand_snippet = on_expand_snippet
        self._is_held = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._release_delay_seconds = 0.03

        self._trigger_parts = self._parse_hotkey(config.trigger)
        self._trigger_key = self._resolve_trigger_key(self._trigger_parts)
        self._required_modifiers = self._trigger_parts - {self._trigger_key}

    def _parse_hotkey(self, hotkey_str: str) -> set[str]:
        """Parse hotkey string like `ctrl+space` into key names."""
        parts = set()
        for part in hotkey_str.lower().split("+"):
            parts.add(part.strip())
        return parts

    @staticmethod
    def _modifier_aliases(modifier: str) -> tuple[str, ...]:
        """Return accepted aliases for generic modifiers."""
        alias_map = {
            "ctrl": ("ctrl", "left ctrl", "right ctrl"),
            "shift": ("shift", "left shift", "right shift"),
            "alt": ("alt", "left alt", "right alt", "alt gr"),
            "windows": ("windows", "left windows", "right windows"),
        }
        return alias_map.get(modifier, (modifier,))

    def _is_modifier_pressed(self, modifier: str) -> bool:
        """Check whether a modifier or any of its sided variants is pressed."""
        return any(keyboard.is_pressed(alias) for alias in self._modifier_aliases(modifier))

    @staticmethod
    def _resolve_trigger_key(parts: set[str]) -> str:
        """Return the non-modifier key that should drive press/release events."""
        modifiers = {
            "ctrl",
            "left ctrl",
            "right ctrl",
            "shift",
            "left shift",
            "right shift",
            "alt",
            "left alt",
            "right alt",
            "windows",
            "left windows",
            "right windows",
        }
        non_modifiers = [part for part in parts if part not in modifiers]
        if not non_modifiers:
            raise ValueError("Trigger hotkey must include a non-modifier key")
        return non_modifiers[-1]

    def start(self):
        """Start listening for hotkeys."""
        self._running = True

        keyboard.on_press_key(self._trigger_key, self._on_trigger_press, suppress=False)
        keyboard.on_release_key(self._trigger_key, self._on_trigger_release, suppress=False)

        if self.config.clipboard_toggle.strip():
            keyboard.add_hotkey(
                self.config.clipboard_toggle,
                self._on_mode_toggle,
                suppress=True,
            )

        if self.config.expand_snippet.strip() and self._on_expand_snippet:
            try:
                keyboard.add_hotkey(
                    self.config.expand_snippet,
                    lambda: threading.Thread(
                        target=self._on_expand_snippet, daemon=True,
                        name="koe-expand-snippet",
                    ).start(),
                    suppress=True,
                )
            except Exception as exc:
                logger.warning("Cannot register expand_snippet hotkey: %s", exc)

        logger.info(
            "Hotkeys registered: trigger=%s, toggle=%s",
            self.config.trigger,
            self.config.clipboard_toggle or "disabled",
        )

    def _on_trigger_press(self, event):
        """Handle trigger key press."""
        if not all(self._is_modifier_pressed(modifier) for modifier in self._required_modifiers):
            return

        if self._is_held:
            return

        self._is_held = True
        logger.debug("Hotkey pressed - starting recording")

        threading.Thread(target=self._on_record_start, daemon=True).start()

    def _on_trigger_release(self, event):
        """Handle trigger key release."""
        if not self._is_held:
            return

        self._is_held = False
        logger.debug("Hotkey released - stopping recording")

        threading.Thread(target=self._delayed_record_stop, daemon=True).start()

    def _delayed_record_stop(self):
        """Wait briefly so modifier keys can settle before delivery."""
        time.sleep(self._release_delay_seconds)
        self._on_record_stop()

    def stop(self):
        """Stop listening for hotkeys."""
        self._running = False
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        logger.info("Hotkey listener stopped")
