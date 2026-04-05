"""Koe recording overlay.

Design based on the VoiceVisualizer reference:
  - Solid black pill (#121212), shadow-2xl
  - 11 symmetric bars, white-to-gray-300 gradient fill
  - Natural random jitter animation when speaking
  - Idle: bars collapse to small resting curve
  - Processing: three pulsing dots
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import math
import random
import threading
import time
from enum import Enum
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger(__name__)

# ── Win32 constants ───────────────────────────────────────────────────────────
_WS_POPUP          = 0x80000000
_WS_EX_LAYERED     = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW  = 0x00000080
_WS_EX_NOACTIVATE  = 0x08000000
_WS_EX_TOPMOST     = 0x00000008
_SW_HIDE           = 0
_SW_SHOWNOACTIVATE = 4
_ULW_ALPHA         = 0x00000002
_AC_SRC_OVER       = 0x00
_AC_SRC_ALPHA      = 0x01

# ── Win32 structures ──────────────────────────────────────────────────────────
class _POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]

class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]

class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp",             ctypes.c_byte),
        ("BlendFlags",          ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat",         ctypes.c_byte),
    ]

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",          wt.DWORD), ("biWidth",         wt.LONG),
        ("biHeight",        wt.LONG),  ("biPlanes",        wt.WORD),
        ("biBitCount",      wt.WORD),  ("biCompression",   wt.DWORD),
        ("biSizeImage",     wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),  ("biClrUsed",       wt.DWORD),
        ("biClrImportant",  wt.DWORD),
    ]

class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("style", wt.UINT),
        ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON), ("hCursor", ctypes.c_void_p),
        ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON),
    ]

_WNDPROCTYPE = ctypes.WINFUNCTYPE(
    ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
)

# ── Supersampling ─────────────────────────────────────────────────────────────
# We render at 2× then downscale with LANCZOS — eliminates all aliasing.
_SCALE  = 2

# ── Pill geometry (display pixels) ────────────────────────────────────────────
_PILL_W = 104
_PILL_H = 30
_PAD    = 20         # window padding for shadow bleed
_WIN_W  = _PILL_W + _PAD * 2   # 144  — display resolution
_WIN_H  = _PILL_H + _PAD * 2   # 70
_TOP_Y  = 10

# Render-space equivalents (2×)
_R_PILL_W = _PILL_W * _SCALE
_R_PILL_H = _PILL_H * _SCALE
_R_PAD    = _PAD    * _SCALE
_R_WIN_W  = _WIN_W  * _SCALE
_R_WIN_H  = _WIN_H  * _SCALE

# ── Bar geometry (in render space = 2×) ───────────────────────────────────────
_BAR_COUNT = 11
_BAR_W     = 5       # render-px wide  → 2.5 px displayed
_BAR_GAP   = 4       # render-px gap   → 2 px displayed
_BAR_SPAN  = _BAR_COUNT * _BAR_W + (_BAR_COUNT - 1) * _BAR_GAP  # 127 render-px

# Bar height in render-px
_BAR_AREA_H = _R_PILL_H - 20   # render-px available for bars
_BAR_MAX_H  = _BAR_AREA_H
_BAR_MIN_H  = 6                 # floor (render-px)

# Symmetric resting profile — matches React initial heights / 100
_BAR_BASE = [0.20, 0.35, 0.55, 0.75, 0.90, 1.00, 0.90, 0.75, 0.55, 0.35, 0.20]

# ── Colours ───────────────────────────────────────────────────────────────────
_PILL_COLOR  = (18, 18, 18, 255)        # #121212
_BAR_TOP_RGB = (255, 255, 255)          # white (top of gradient)
_BAR_BOT_RGB = (209, 213, 219)          # Tailwind gray-300 (bottom of gradient)
_DOT_ON      = (220, 220, 220, 220)
_DOT_OFF     = (60, 60, 65, 90)
_DOT_R       = 4
_DOT_GAP     = 12

# ── Spring & frame rate ───────────────────────────────────────────────────────
_SPRING_K    = 0.22
_SPRING_DAMP = 0.62
_FRAME_S     = 1 / 30

# ── Animation ─────────────────────────────────────────────────────────────────
_LERP_K       = 0.35      # bar lerp rate per frame (~100 ms settle)
_JITTER_EVERY = 3         # update random targets every N frames (~100 ms)
_K_ATTACK     = 0.32
_K_RELEASE    = 0.08
_ACTIVE_GATE  = 0.03


class OverlayState(Enum):
    HIDDEN     = "hidden"
    RECORDING  = "recording"
    PROCESSING = "processing"


class Overlay:
    """Floating black pill — 11-bar symmetric waveform visualiser."""

    def __init__(self, position: str = "top-center", hotkey_hint: str = "ALT + K"):
        self._position    = position
        self._hotkey_hint = hotkey_hint

        self._state:        OverlayState = OverlayState.HIDDEN
        self._target_state: OverlayState = OverlayState.HIDDEN

        self._hide_y = float(-(_WIN_H + 40))
        self._rest_y = float(_TOP_Y)
        self._y_pos  = self._hide_y
        self._y_vel  = 0.0

        self._win_visible   = False
        self._phase         = 0.0
        self._energy        = 0.0
        self._bar_heights   = list(_BAR_BASE)      # current rendered heights (0-1)
        self._bar_targets   = list(_BAR_BASE)      # lerp targets
        self._jitter_clock  = 0

        self.rms_source: Optional[Callable[[], float]] = None

        self._lock    = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._hwnd: int = 0
        self._mem_dc: int = 0
        self._hbitmap: int = 0
        self._bits_ptr: ctypes.c_void_p = ctypes.c_void_p(0)
        self._screen_dc: int = 0
        self._wnd_proc_cb = None
        self._cls_name    = f"KoeOverlay_{id(self)}"

        # Pre-compute the vertical gradient lookup (white→gray-300)
        self._grad_r, self._grad_g, self._grad_b = self._build_gradient()

    # ── Gradient lookup ───────────────────────────────────────────────────────

    @staticmethod
    def _build_gradient():
        """Build per-row RGB arrays for the white→gray-300 bar gradient (render space)."""
        H = _R_WIN_H
        t = np.linspace(0.0, 1.0, H)
        r = (_BAR_TOP_RGB[0] * (1-t) + _BAR_BOT_RGB[0] * t).astype(np.uint8)
        g = (_BAR_TOP_RGB[1] * (1-t) + _BAR_BOT_RGB[1] * t).astype(np.uint8)
        b = (_BAR_TOP_RGB[2] * (1-t) + _BAR_BOT_RGB[2] * t).astype(np.uint8)
        return r, g, b

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name="koe-overlay"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def set_state(self, state: OverlayState):
        with self._lock:
            self._target_state = state

    @property
    def state(self) -> OverlayState:
        return self._state

    # ── Thread entry ──────────────────────────────────────────────────────────

    def _run(self):
        try:
            self._setup_win32()
            self._loop()
        except Exception:
            logger.exception("Overlay thread crashed")
        finally:
            self._teardown_win32()

    # ── Win32 window lifecycle ────────────────────────────────────────────────

    def _setup_win32(self):
        u32   = ctypes.windll.user32
        k32   = ctypes.windll.kernel32
        gdi32 = ctypes.windll.gdi32
        hinst = k32.GetModuleHandleW(None)

        @_WNDPROCTYPE
        def _wnd_proc(hwnd, msg, wparam, lparam):
            return 1 if msg == 0x0081 else 0   # WM_NCCREATE → 1

        self._wnd_proc_cb = _wnd_proc

        wc = _WNDCLASSEXW()
        wc.cbSize        = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc   = ctypes.cast(self._wnd_proc_cb, ctypes.c_void_p)
        wc.hInstance     = hinst
        wc.lpszClassName = self._cls_name
        wc.hbrBackground = 0

        if not u32.RegisterClassExW(ctypes.byref(wc)):
            raise RuntimeError(f"RegisterClassExW failed: {ctypes.GetLastError()}")

        sw = u32.GetSystemMetrics(0)
        hwnd = u32.CreateWindowExW(
            _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW
            | _WS_EX_NOACTIVATE | _WS_EX_TOPMOST,
            self._cls_name, "KoeOverlay", _WS_POPUP,
            (sw - _WIN_W) // 2, int(self._y_pos), _WIN_W, _WIN_H,
            0, 0, hinst, 0,
        )
        if not hwnd:
            raise RuntimeError(f"CreateWindowExW failed: {ctypes.GetLastError()}")
        self._hwnd = hwnd

        self._screen_dc = u32.GetDC(None)
        self._mem_dc    = gdi32.CreateCompatibleDC(self._screen_dc)

        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = _WIN_W; bmi.biHeight = -_WIN_H
        bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0

        bits_ptr = ctypes.c_void_p()
        hbitmap  = gdi32.CreateDIBSection(
            self._mem_dc, ctypes.byref(bmi), 0,
            ctypes.byref(bits_ptr), None, 0,
        )
        if not hbitmap:
            raise RuntimeError("CreateDIBSection failed")
        gdi32.SelectObject(self._mem_dc, hbitmap)
        self._hbitmap  = hbitmap
        self._bits_ptr = bits_ptr

    def _teardown_win32(self):
        gdi32 = ctypes.windll.gdi32
        u32   = ctypes.windll.user32
        if self._hwnd:    u32.DestroyWindow(self._hwnd);      self._hwnd    = 0
        if self._hbitmap: gdi32.DeleteObject(self._hbitmap);  self._hbitmap = 0
        if self._mem_dc:  gdi32.DeleteDC(self._mem_dc);       self._mem_dc  = 0
        if self._screen_dc:
            u32.ReleaseDC(None, self._screen_dc); self._screen_dc = 0
        try:
            u32.UnregisterClassW(
                self._cls_name, ctypes.windll.kernel32.GetModuleHandleW(None)
            )
        except Exception:
            pass

    # ── Animation loop ────────────────────────────────────────────────────────

    def _loop(self):
        last_t = time.monotonic()
        while self._running:
            t  = time.monotonic()
            dt = t - last_t
            if dt < _FRAME_S:
                time.sleep(_FRAME_S - dt)
                continue
            last_t = t
            self._phase += dt * 5.0

            with self._lock:
                self._state = self._target_state

            self._step_spring(self._state != OverlayState.HIDDEN)
            self._update_bars()

            if self._win_visible:
                self._ulw_blit(self._render_frame())

    # ── Spring entrance ───────────────────────────────────────────────────────

    def _step_spring(self, visible: bool):
        target      = self._rest_y if visible else self._hide_y
        self._y_vel = self._y_vel * _SPRING_DAMP + (target - self._y_pos) * _SPRING_K
        self._y_pos += self._y_vel
        if visible:
            self._y_pos = min(self._y_pos, self._rest_y + 8)

        fully_hidden = self._y_pos < (self._hide_y + 5)
        u32 = ctypes.windll.user32
        if fully_hidden:
            if self._win_visible:
                u32.ShowWindow(self._hwnd, _SW_HIDE)
                self._win_visible = False
        else:
            if not self._win_visible:
                u32.ShowWindow(self._hwnd, _SW_SHOWNOACTIVATE)
                self._win_visible = True
            sw = u32.GetSystemMetrics(0)
            u32.SetWindowPos(
                self._hwnd, 0,
                (sw - _WIN_W) // 2, max(-_WIN_H, int(self._y_pos)),
                0, 0, 0x0001 | 0x0004 | 0x0010,
            )

    # ── Bar animation ─────────────────────────────────────────────────────────

    def _get_rms(self) -> float:
        if self.rms_source is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(self.rms_source())))
        except Exception:
            return 0.0

    def _update_bars(self):
        is_rec = self._state == OverlayState.RECORDING
        raw    = self._get_rms() if is_rec else 0.0

        # Smooth energy envelope
        tgt_e = min(1.0, raw * 40.0)
        k_env = _K_ATTACK if tgt_e > self._energy else _K_RELEASE
        self._energy += (tgt_e - self._energy) * k_env

        is_active = self._energy > _ACTIVE_GATE

        # Update jitter targets every _JITTER_EVERY frames (~100 ms)
        self._jitter_clock += 1
        if self._jitter_clock >= _JITTER_EVERY:
            self._jitter_clock = 0
            for i in range(_BAR_COUNT):
                base = _BAR_BASE[i]
                if is_rec and is_active:
                    # Scale jitter amplitude with energy, keep bell-curve shape
                    amp    = min(1.0, self._energy * 2.0)
                    jitter = (random.random() * 2 - 1) * 0.30 * amp
                    self._bar_targets[i] = max(
                        0.08, min(1.0, base * amp + base * 0.25 + jitter)
                    )
                elif is_rec:
                    # Listening but silent — very small resting curve
                    self._bar_targets[i] = base * 0.18
                else:
                    self._bar_targets[i] = 0.0

        # Lerp current heights toward targets
        for i in range(_BAR_COUNT):
            self._bar_heights[i] += (
                self._bar_targets[i] - self._bar_heights[i]
            ) * _LERP_K

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_frame(self) -> Image.Image:
        """Render at 2× then downscale with LANCZOS for smooth, alias-free edges."""
        W, H = _R_WIN_W, _R_WIN_H   # render space
        px   = _R_PAD
        py   = _R_PAD
        pw   = _R_PILL_W
        ph   = _R_PILL_H
        r    = ph // 2
        cx   = px + pw // 2
        cy   = py + ph // 2

        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        # pill body
        ImageDraw.Draw(img).rounded_rectangle(
            [px, py, px + pw, py + ph], radius=r, fill=_PILL_COLOR,
        )

        # content
        if self._state == OverlayState.RECORDING:
            img = self._render_bars(img, cx, cy, W, H)
        elif self._state == OverlayState.PROCESSING:
            img = self._render_dots(img, cx, cy)

        # Downscale to display resolution — LANCZOS removes all aliasing
        return img.resize((_WIN_W, _WIN_H), Image.LANCZOS)

    def _render_bars(self, img: Image.Image, cx: int, cy: int,
                     W: int, H: int) -> Image.Image:
        """11 bars with white→gray-300 gradient, rendered in 2× space."""
        sx = cx - _BAR_SPAN // 2

        bar_mask = Image.new("L", (W, H), 0)
        md       = ImageDraw.Draw(bar_mask)

        for i in range(_BAR_COUNT):
            h_f  = max(0.0, self._bar_heights[i])
            h_px = max(_BAR_MIN_H, int(_BAR_MAX_H * h_f))
            bx   = sx + i * (_BAR_W + _BAR_GAP)
            by1  = cy - h_px // 2
            by2  = cy + h_px // 2
            md.rounded_rectangle([bx, by1, bx + _BAR_W, by2], radius=3, fill=255)

        # Gradient (H rows) broadcast to (H, W) — numpy is fast
        grad_rgba        = np.zeros((H, W, 4), dtype=np.uint8)
        grad_rgba[:, :, 0] = self._grad_r[:, None]
        grad_rgba[:, :, 1] = self._grad_g[:, None]
        grad_rgba[:, :, 2] = self._grad_b[:, None]
        grad_rgba[:, :, 3] = np.array(bar_mask)

        return Image.alpha_composite(img, Image.fromarray(grad_rgba, "RGBA"))

    def _render_dots(self, img: Image.Image, cx: int, cy: int) -> Image.Image:
        """Three pulsing dots for the PROCESSING state (render space)."""
        dot_r = _DOT_R * _SCALE
        gap   = _DOT_GAP * _SCALE
        n     = 3
        w     = n * (dot_r * 2) + (n - 1) * gap
        sx    = cx - w // 2
        draw  = ImageDraw.Draw(img)
        for i in range(n):
            t = (math.sin(self._phase * 1.8 - i * 1.1) + 1) / 2
            r = int(_DOT_OFF[0] + (_DOT_ON[0] - _DOT_OFF[0]) * t)
            g = int(_DOT_OFF[1] + (_DOT_ON[1] - _DOT_OFF[1]) * t)
            b = int(_DOT_OFF[2] + (_DOT_ON[2] - _DOT_OFF[2]) * t)
            a = int(_DOT_OFF[3] + (_DOT_ON[3] - _DOT_OFF[3]) * t)
            bx = sx + i * (dot_r * 2 + gap)
            draw.ellipse([bx, cy - dot_r, bx + dot_r * 2, cy + dot_r],
                         fill=(r, g, b, a))
        return img

    # ── UpdateLayeredWindow blit ──────────────────────────────────────────────

    def _ulw_blit(self, image: Image.Image):
        u32   = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        rgba    = np.asarray(image, dtype=np.uint8).copy()
        alpha_f = rgba[:, :, 3:4].astype(np.float32) / 255.0
        bgra    = np.stack([
            (rgba[:, :, 2] * alpha_f[:, :, 0]).astype(np.uint8),
            (rgba[:, :, 1] * alpha_f[:, :, 0]).astype(np.uint8),
            (rgba[:, :, 0] * alpha_f[:, :, 0]).astype(np.uint8),
            rgba[:, :, 3],
        ], axis=2)

        ctypes.memmove(self._bits_ptr, bgra.tobytes(), bgra.nbytes)

        sw     = u32.GetSystemMetrics(0)
        x      = (sw - _WIN_W) // 2
        y      = max(-_WIN_H, int(self._y_pos))
        pt_dst = _POINT(x, y)
        pt_src = _POINT(0, 0)
        win_sz = _SIZE(_WIN_W, _WIN_H)
        blend  = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)

        u32.UpdateLayeredWindow(
            self._hwnd, self._screen_dc,
            ctypes.byref(pt_dst), ctypes.byref(win_sz),
            self._mem_dc, ctypes.byref(pt_src),
            0, ctypes.byref(blend), _ULW_ALPHA,
        )
