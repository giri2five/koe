"""Global hotkey listener for Koe.

Detects hold-to-talk using the configured trigger key combination.
Uses the `keyboard` library with suppress=False for all hotkeys.

suppress=False means no WH_KEYBOARD_LL key swallowing — modifier keys
(Alt, Ctrl, Shift) can NEVER get stuck in other applications.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Callable, Optional

import keyboard

from koe.config import HotkeyConfig

logger = logging.getLogger(__name__)


def _vk_pressed(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


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
        self._on_record_start   = on_record_start
        self._on_record_stop    = on_record_stop
        self._on_mode_toggle    = on_mode_toggle
        self._on_expand_snippet = on_expand_snippet
        self._is_held           = False
        self._running           = False
        self._release_delay_seconds = 0.03

        self._trigger_parts      = self._parse_hotkey(config.trigger)
        self._trigger_key        = self._resolve_trigger_key(self._trigger_parts)
        self._required_modifiers = self._trigger_parts - {self._trigger_key}

        # Expand snippet hotkey parts (parsed once at init)
        self._expand_key:  str       = ""
        self._expand_mods: set[str]  = set()
        if config.expand_snippet.strip():
            try:
                parts = self._parse_hotkey(config.expand_snippet)
                self._expand_key  = self._resolve_trigger_key(parts)
                self._expand_mods = parts - {self._expand_key}
            except ValueError as exc:
                logger.warning("Cannot parse expand hotkey: %s", exc)

    # ── Parsing helpers ────────────────────────────────────────────────────

    def _parse_hotkey(self, hotkey_str: str) -> set[str]:
        return {p.strip() for p in hotkey_str.lower().split("+")}

    @staticmethod
    def _modifier_aliases(modifier: str) -> tuple[str, ...]:
        return {
            "ctrl":    ("ctrl", "left ctrl", "right ctrl"),
            "shift":   ("shift", "left shift", "right shift"),
            "alt":     ("alt", "left alt", "right alt", "alt gr"),
            "windows": ("windows", "left windows", "right windows"),
        }.get(modifier, (modifier,))

    def _is_modifier_pressed(self, modifier: str) -> bool:
        return any(keyboard.is_pressed(a) for a in self._modifier_aliases(modifier))

    @staticmethod
    def _resolve_trigger_key(parts: set[str]) -> str:
        _mods = {
            "ctrl", "left ctrl", "right ctrl",
            "shift", "left shift", "right shift",
            "alt", "left alt", "right alt",
            "windows", "left windows", "right windows",
        }
        non_mods = [p for p in parts if p not in _mods]
        if not non_mods:
            raise ValueError("Hotkey must include a non-modifier key")
        return non_mods[-1]

    # ── Start / stop ───────────────────────────────────────────────────────

    def start(self):
        self._running = True

        # Record trigger (hold-to-talk)
        keyboard.on_press_key(
            self._trigger_key, self._on_trigger_press, suppress=False
        )
        keyboard.on_release_key(
            self._trigger_key, self._on_trigger_release, suppress=False
        )

        # Clipboard-mode toggle
        if self.config.clipboard_toggle.strip():
            keyboard.add_hotkey(
                self.config.clipboard_toggle,
                self._on_mode_toggle,
                suppress=False,
            )

        # Snippet expand — same mechanism as record trigger (suppress=False)
        if self._expand_key and self._on_expand_snippet:
            keyboard.on_press_key(
                self._expand_key, self._on_expand_press, suppress=False
            )
            logger.info(
                "Expand hotkey registered: %s (key=%s mods=%s)",
                self.config.expand_snippet, self._expand_key, self._expand_mods,
            )

        logger.info(
            "Hotkeys registered: trigger=%s, expand=%s",
            self.config.trigger,
            self.config.expand_snippet or "disabled",
        )

    def stop(self):
        self._running = False
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        logger.info("Hotkey listener stopped")

    # ── Record trigger ─────────────────────────────────────────────────────

    def _on_trigger_press(self, event):
        if not all(
            self._is_modifier_pressed(m) for m in self._required_modifiers
        ):
            return
        if self._is_held:
            return
        self._is_held = True
        logger.debug("Hotkey pressed — starting recording")
        threading.Thread(target=self._on_record_start, daemon=True).start()

    def _on_trigger_release(self, event):
        if not self._is_held:
            return
        self._is_held = False
        logger.debug("Hotkey released — stopping recording")
        threading.Thread(target=self._delayed_record_stop, daemon=True).start()

    def _delayed_record_stop(self):
        time.sleep(self._release_delay_seconds)
        self._on_record_stop()

    # ── Snippet expand ─────────────────────────────────────────────────────

    def _on_expand_press(self, event):
        """Fires when the expand key is pressed — check modifiers then expand."""
        if not all(
            self._is_modifier_pressed(m) for m in self._expand_mods
        ):
            return
        if self._on_expand_snippet is None:
            return
        logger.debug("Expand hotkey pressed")
        threading.Thread(
            target=self._on_expand_snippet, daemon=True, name="koe-expand-snippet"
        ).start()
