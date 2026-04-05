"""Global hotkey listener for Koe.

Detects hold-to-talk using the configured trigger key combination.
Uses the `keyboard` library for the record trigger (hold-to-talk).

The snippet-expand hotkey uses Win32 RegisterHotKey instead of the
keyboard library.  RegisterHotKey handles suppression at the OS level
with no WH_KEYBOARD_LL hook involved, so modifier keys (Ctrl/Shift)
can NEVER get stuck in other applications.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
import time
from typing import Callable, Optional

import keyboard

from koe.config import HotkeyConfig

logger = logging.getLogger(__name__)

# ── Win32 constants ────────────────────────────────────────────────────────
_VK_SHIFT   = 0x10
_VK_CONTROL = 0x11
_VK_MENU    = 0x12   # Alt (either side)
_VK_LWIN    = 0x5B

# RegisterHotKey fsModifiers
_MOD_ALT      = 0x0001
_MOD_CONTROL  = 0x0002
_MOD_SHIFT    = 0x0004
_MOD_WIN      = 0x0008
_MOD_NOREPEAT = 0x4000   # don't fire repeatedly while key held

_MODIFIER_TO_MOD = {
    "alt": _MOD_ALT, "ctrl": _MOD_CONTROL, "control": _MOD_CONTROL,
    "shift": _MOD_SHIFT, "win": _MOD_WIN, "windows": _MOD_WIN,
}

_MOD_VK = {
    "shift": _VK_SHIFT, "ctrl": _VK_CONTROL,
    "alt": _VK_MENU,    "windows": _VK_LWIN,
}

WM_HOTKEY = 0x0312
WM_QUIT   = 0x0012


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",     ctypes.c_void_p),
        ("message",  ctypes.c_uint),
        ("wParam",   ctypes.c_size_t),
        ("lParam",   ctypes.c_ssize_t),
        ("time",     ctypes.c_uint),
        ("pt",       wt.POINT),
        ("lPrivate", ctypes.c_uint),
    ]


def _vk_pressed(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _key_name_to_vk(name: str) -> int | None:
    n = name.strip().lower()
    if len(n) == 1 and n.isalpha():
        return ord(n.upper())
    if len(n) == 1 and n.isdigit():
        return ord(n)
    return {
        "space": 0x20, "enter": 0x0D, "return": 0x0D,
        "tab": 0x09, "backspace": 0x08, "esc": 0x1B, "escape": 0x1B,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
        "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
        "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    }.get(n)


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

        self._trigger_parts     = self._parse_hotkey(config.trigger)
        self._trigger_key       = self._resolve_trigger_key(self._trigger_parts)
        self._required_modifiers = self._trigger_parts - {self._trigger_key}

        # RegisterHotKey state
        self._reg_thread_id: int | None = None
        self._reg_thread: threading.Thread | None = None

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

        # Record trigger (hold-to-talk) — keyboard library
        keyboard.on_press_key(
            self._trigger_key, self._on_trigger_press, suppress=False
        )
        keyboard.on_release_key(
            self._trigger_key, self._on_trigger_release, suppress=False
        )

        if self.config.clipboard_toggle.strip():
            keyboard.add_hotkey(
                self.config.clipboard_toggle,
                self._on_mode_toggle,
                suppress=True,
            )

        # Snippet expand — RegisterHotKey (no WH_KEYBOARD_LL, no stuck keys)
        if self.config.expand_snippet.strip() and self._on_expand_snippet:
            self._start_register_hotkey()

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
        self._stop_register_hotkey()
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

    # ── Snippet expand (RegisterHotKey) ───────────────────────────────────

    def _start_register_hotkey(self):
        """Parse config and spin up the RegisterHotKey message-loop thread."""
        try:
            parts   = self._parse_hotkey(self.config.expand_snippet)
            key     = self._resolve_trigger_key(parts)
            mods    = parts - {key}

            vk = _key_name_to_vk(key)
            if vk is None:
                raise ValueError(f"Unknown key name: {key!r}")

            fs = _MOD_NOREPEAT
            for m in mods:
                mod_val = _MODIFIER_TO_MOD.get(m)
                if mod_val is None:
                    raise ValueError(f"Unknown modifier: {m!r}")
                fs |= mod_val

        except ValueError as exc:
            logger.warning("Cannot register expand hotkey: %s", exc)
            return

        self._reg_thread = threading.Thread(
            target=self._register_hotkey_loop,
            args=(1, fs, vk),
            daemon=True,
            name="koe-expand-hotkey",
        )
        self._reg_thread.start()

    def _register_hotkey_loop(self, hotkey_id: int, fs_mods: int, vk: int):
        """
        Thread: registers a Win32 hotkey and pumps messages.

        RegisterHotKey suppresses the key combination at the OS level —
        no WH_KEYBOARD_LL hook, so Ctrl/Shift can never get stuck.
        """
        u32 = ctypes.windll.user32

        if not u32.RegisterHotKey(None, hotkey_id, fs_mods, vk):
            err = ctypes.windll.kernel32.GetLastError()
            logger.warning(
                "RegisterHotKey failed (err=%d) for hotkey id=%d", err, hotkey_id
            )
            return

        # Store thread ID so stop() can post WM_QUIT
        self._reg_thread_id = u32.GetCurrentThreadId()
        logger.debug("RegisterHotKey loop started (thread_id=%d)", self._reg_thread_id)

        msg = _MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                threading.Thread(
                    target=self._on_expand_snippet, daemon=True,
                    name="koe-expand-snippet",
                ).start()

        u32.UnregisterHotKey(None, hotkey_id)
        logger.debug("RegisterHotKey loop stopped")

    def _stop_register_hotkey(self):
        tid = self._reg_thread_id
        if tid:
            ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            self._reg_thread_id = None
