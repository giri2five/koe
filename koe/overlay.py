"""Live recording overlay for Koe - pure tkinter + Win32, no pythonnet.

Renders a small pill capsule at the top-center of the primary display.
- iOS-style spring entrance/exit animation (slight overshoot on show)
- Live waveform bars driven by real audio RMS
- Processing state with cascading dot animation
- Click-through, always-on-top, no taskbar entry
"""
from __future__ import annotations

import logging
import math
import threading
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_GWL_EXSTYLE       = -20
_WS_EX_LAYERED     = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW  = 0x00000080
_WS_EX_NOACTIVATE  = 0x08000000

_PILL_W = 196
_PILL_H = 52
_PAD    = 8
_WIN_W  = _PILL_W + _PAD * 2
_WIN_H  = _PILL_H + _PAD * 2
_TOP_Y  = 20

_CHROMA     = "#010102"
_PILL_FILL  = "#0d0d12"
_PILL_GLOSS = "#15151e"
_BAR_BRIGHT = "#f0eeea"
_BAR_DIM    = "#484852"
_DOT_ON     = "#e8e6e2"
_DOT_OFF    = "#2a2a34"
_WIN_ALPHA  = 0.94

_SPRING_K    = 0.26
_SPRING_DAMP = 0.66
_FADE_IN     = 0.24
_FADE_OUT    = 0.20


class OverlayState(Enum):
    HIDDEN     = "hidden"
    RECORDING  = "recording"
    PROCESSING = "processing"


class Overlay:
    """Small pill overlay shown while recording and processing."""

    def __init__(self, position: str = "top-center", hotkey_hint: str = "ALT + K"):
        self._position    = position
        self._hotkey_hint = hotkey_hint
        self._state:        OverlayState = OverlayState.HIDDEN
        self._target_state: OverlayState = OverlayState.HIDDEN
        self._y_pos = float(-(_PILL_H + _PAD + 30))
        self._y_vel = 0.0
        self._opacity     = 0.0
        self._win_visible = False
        self._phase       = 0.0
        self._smoothed_rms = 0.18
        self._bar_heights  = [5.0] * 9
        self.rms_source: Optional[Callable[[], float]] = None
        self._lock    = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._root   = None
        self._canvas = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="koe-overlay")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._root is not None:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def set_state(self, state: OverlayState):
        with self._lock:
            self._target_state = state

    @property
    def state(self) -> OverlayState:
        return self._state

    def _run(self):
        try:
            import tkinter as tk
            self._root = tk.Tk()
            self._setup_window()
            self._canvas = tk.Canvas(self._root, width=_WIN_W, height=_WIN_H,
                                      bg=_CHROMA, highlightthickness=0, bd=0)
            self._canvas.pack()
            self._position_window()
            self._root.withdraw()
            self._schedule()
            self._root.mainloop()
        except Exception as exc:
            logger.error("Overlay crashed: %s", exc, exc_info=True)

    def _setup_window(self):
        r = self._root
        r.overrideredirect(True)
        r.wm_attributes("-topmost", True)
        r.wm_attributes("-alpha", 0.0)
        r.configure(bg=_CHROMA)
        try:
            r.wm_attributes("-transparentcolor", _CHROMA)
        except Exception:
            pass
        r.update_idletasks()
        try:
            import ctypes
            hwnd   = r.winfo_id()
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ex |= _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE | _WS_EX_TRANSPARENT | _WS_EX_LAYERED
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex)
        except Exception:
            pass

    def _position_window(self):
        sw = self._root.winfo_screenwidth()
        x  = (sw - _WIN_W) // 2
        self._root.geometry(f"{_WIN_W}x{_WIN_H}+{x}+{int(self._y_pos)}")

    def _schedule(self):
        if self._root is not None:
            self._root.after(14, self._frame)

    def _frame(self):
        if not self._running:
            try:
                self._root.destroy()
            except Exception:
                pass
            return
        self._phase += 0.11
        with self._lock:
            self._state = self._target_state
        visible = self._state != OverlayState.HIDDEN
        self._animate(visible)
        self._draw()
        self._schedule()

    def _animate(self, visible: bool):
        sw     = self._root.winfo_screenwidth()
        x      = (sw - _WIN_W) // 2
        rest_y = float(_TOP_Y - _PAD)
        hide_y = float(-(_PILL_H + _PAD + 28))
        target = rest_y if visible else hide_y

        force        = (target - self._y_pos) * _SPRING_K
        self._y_vel  = self._y_vel * _SPRING_DAMP + force
        self._y_pos += self._y_vel
        if visible:
            self._y_pos = min(self._y_pos, rest_y + 8)

        target_alpha = _WIN_ALPHA if visible else 0.0
        rate         = _FADE_IN if visible else _FADE_OUT
        self._opacity += (target_alpha - self._opacity) * rate
        alpha = max(0.0, min(1.0, self._opacity))

        if alpha < 0.012:
            if self._win_visible:
                self._root.withdraw()
                self._win_visible = False
        else:
            if not self._win_visible:
                self._root.deiconify()
                self._win_visible = True
            self._root.geometry(f"{_WIN_W}x{_WIN_H}+{x}+{int(self._y_pos)}")
            try:
                self._root.wm_attributes("-alpha", alpha)
            except Exception:
                pass

        raw = self._get_rms() if self._state == OverlayState.RECORDING else 0.0
        self._smoothed_rms += (raw - self._smoothed_rms) * 0.3
        self._update_bars()

    def _get_rms(self) -> float:
        if self.rms_source is None:
            return 0.18
        try:
            return max(0.06, min(1.0, float(self.rms_source()) * 13))
        except Exception:
            return 0.18

    def _update_bars(self):
        bases = [5, 8, 13, 19, 23, 19, 13, 8, 5]
        for i, base in enumerate(bases):
            pulse  = 0.78 + 0.22 * math.sin(self._phase * 2.6 + i * 0.62)
            level  = max(0.10, self._smoothed_rms)
            target = max(3.0, base * level * pulse)
            self._bar_heights[i] += (target - self._bar_heights[i]) * 0.24

    def _draw(self):
        c = self._canvas
        c.delete("all")
        if self._opacity < 0.012:
            return
        px, py = _PAD, _PAD
        pw, ph = _PILL_W, _PILL_H
        self._draw_pill(c, px, py, pw, ph)
        cx = px + pw // 2
        cy = py + ph // 2
        if self._state == OverlayState.RECORDING:
            self._draw_bars(c, cx, cy)
        elif self._state == OverlayState.PROCESSING:
            self._draw_dots(c, cx, cy)

    def _draw_pill(self, c, x, y, w, h):
        r = h // 2
        f = _PILL_FILL
        c.create_oval(x, y, x + 2*r, y + h, fill=f, outline="")
        c.create_oval(x + w - 2*r, y, x + w, y + h, fill=f, outline="")
        c.create_rectangle(x + r, y, x + w - r, y + h, fill=f, outline="")
        gcx = x + w // 2
        c.create_oval(gcx - 24, y + 2, gcx + 24, y + 14, fill=_PILL_GLOSS, outline="")
        if w > 40:
            c.create_line(x + r + 8, y + 4, x + w - r - 8, y + 4,
                          fill="#ffffff", width=1, capstyle="round")

    def _draw_bars(self, c, cx, cy):
        n = 9; bar_w = 3; gap = 2
        sx = cx - (n * bar_w + (n - 1) * gap) // 2
        for i, h in enumerate(self._bar_heights):
            h   = max(3, int(h))
            bx  = sx + i * (bar_w + gap)
            col = _BAR_BRIGHT if 2 <= i <= 6 else _BAR_DIM
            y1  = cy - h // 2
            y2  = cy + h // 2
            c.create_rectangle(bx, y1 + 1, bx + bar_w, y2 - 1, fill=col, outline="")
            c.create_oval(bx, y1, bx + bar_w, y1 + bar_w, fill=col, outline="")
            c.create_oval(bx, y2 - bar_w, bx + bar_w, y2, fill=col, outline="")

    def _draw_dots(self, c, cx, cy):
        n = 3; dot_d = 7; gap = 10
        sx     = cx - (n * dot_d + (n - 1) * gap) // 2
        active = int((self._phase * 1.5) % n)
        for i in range(n):
            bx  = sx + i * (dot_d + gap)
            col = _DOT_ON if i == active else _DOT_OFF
            c.create_oval(bx, cy - dot_d // 2, bx + dot_d, cy + dot_d // 2,
                          fill=col, outline="")
