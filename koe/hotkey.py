"""Global hotkey listener for Koe.

Detects hold-to-talk using the configured trigger key combination.
Uses the `keyboard` library for the record trigger (hold-to-talk).

The snippet-expand hotkey uses a GetAsyncKeyState polling loop instead
of any keyboard hook.  Polling reads raw physical key state directly from
Windows — no hook, no suppress, nothing can intercept or stick.
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

# ── Win32 VK constants ────────────────────────────────────────────────────────
_VK_SHIFT   = 0x10
_VK_CONTROL = 0x11
_VK_MENU    = 0x12   # Any Alt

_MOD_VK = {
    "shift":   _VK_SHIFT,
    "ctrl":    _VK_CONTROL,
    "control": _VK_CONTROL,
    "alt":     _VK_MENU,
}


def _key_name_to_vk(name: str) -> int | None:
    """Map a key name string to a Windows Virtual-Key code."""
    n = name.strip().lower()
    if len(n) == 1 and n.isalpha():
        return ord(n.upper())
    if len(n) == 1 and n.isdigit():
        return ord(n)
    return {
        "space": 0x20, "enter": 0x0D, "return": 0x0D,
        "tab": 0x09,   "backspace": 0x08, "esc": 0x1B, "escape": 0x1B,
        "f1":  0x70,   "f2": 0x71,  "f3": 0x72,  "f4": 0x73,
        "f5":  0x74,   "f6": 0x75,  "f7": 0x76,  "f8": 0x77,
        "f9":  0x78,   "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    }.get(n)


def _vk_down(vk: int) -> bool:
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

        # Expand hotkey — resolved to VK codes for polling
        self._expand_key_vk:  int | None  = None
        self._expand_mod_vks: list[int]   = []
        self._poll_thread:    threading.Thread | None = None

        if config.expand_snippet.strip():
            self._resolve_expand_vks(config.expand_snippet)

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

    def _resolve_expand_vks(self, hotkey_str: str):
        """Parse expand hotkey into VK codes for polling."""
        try:
            parts   = self._parse_hotkey(hotkey_str)
            key     = self._resolve_trigger_key(parts)
            mods    = parts - {key}

            vk = _key_name_to_vk(key)
            if vk is None:
                raise ValueError(f"Unknown key name: {key!r}")

            mod_vks = []
            for m in mods:
                mvk = _MOD_VK.get(m)
                if mvk is None:
                    raise ValueError(f"Unknown modifier: {m!r}")
                mod_vks.append(mvk)

            self._expand_key_vk  = vk
            self._expand_mod_vks = mod_vks
            logger.info(
                "Expand hotkey: %s → key_vk=0x%02X mods_vk=%s",
                hotkey_str, vk, [f"0x{v:02X}" for v in mod_vks],
            )
        except ValueError as exc:
            logger.warning("Cannot resolve expand hotkey: %s", exc)

    # ── Start / stop ───────────────────────────────────────────────────────

    def start(self):
        self._running = True

        # Record trigger (hold-to-talk) — keyboard library
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

        # Snippet expand — GetAsyncKeyState polling (no hook, nothing can intercept)
        if self._expand_key_vk is not None and self._on_expand_snippet:
            self._poll_thread = threading.Thread(
                target=self._expand_poll_loop,
                daemon=True,
                name="koe-expand-poll",
            )
            self._poll_thread.start()

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
        # Poll thread exits on its own when _running → False
        logger.info("Hotkey listener stopped")

    # ── Record trigger (keyboard library) ─────────────────────────────────

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

    # ── Snippet expand (GetAsyncKeyState polling) ──────────────────────────

    def _expand_poll_loop(self):
        """
        Poll physical key state every 10 ms.

        GetAsyncKeyState reads raw hardware state — no hook involved,
        no suppress, no chance of keys getting stuck or being intercepted.
        Fires once per press (edge-triggered: False → True transition).
        """
        key_vk   = self._expand_key_vk
        mod_vks  = self._expand_mod_vks
        was_down = False

        while self._running:
            # All modifier VKs must be held AND the main key must be down
            combo_down = (
                all(_vk_down(vk) for vk in mod_vks)
                and _vk_down(key_vk)
            )

            if combo_down and not was_down:
                logger.debug("Expand hotkey fired (poll)")
                # Capture the focused window RIGHT NOW — before Left Alt's
                # menu-bar activation can steal focus away from the text.
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                threading.Thread(
                    target=self._on_expand_snippet,
                    args=(hwnd,),
                    daemon=True,
                    name="koe-expand-snippet",
                ).start()

            was_down = combo_down
            time.sleep(0.01)   # 10 ms — responsive but negligible CPU
