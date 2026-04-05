"""Global hotkey listener for Koe.

Detects hold-to-talk using the configured trigger key combination.
Uses the `keyboard` library for global hook on Windows.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import keyboard

from koe.config import HotkeyConfig

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
                expand_parts = self._parse_hotkey(self.config.expand_snippet)
                expand_key   = self._resolve_trigger_key(expand_parts)
                expand_mods  = expand_parts - {expand_key}

                def _on_expand_press(event):
                    if all(self._is_modifier_pressed(m) for m in expand_mods):
                        threading.Thread(
                            target=self._on_expand_snippet, daemon=True,
                            name="koe-expand-snippet",
                        ).start()

                keyboard.on_press_key(expand_key, _on_expand_press, suppress=False)
            except ValueError:
                logger.warning("Invalid expand_snippet hotkey: %s", self.config.expand_snippet)

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
