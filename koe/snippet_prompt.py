"""Floating prompt that appears near the cursor offering snippet expansion.

Uses a minimal Win32 window (no extra dependencies) positioned near the
mouse cursor. Shown after Koe delivers text that contains a snippet trigger.
The user can press Tab to accept (replace text + expand) or Esc/wait to skip.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_u32 = ctypes.windll.user32
_gdi = ctypes.windll.gdi32
_ker = ctypes.windll.kernel32

_CLASS_NAME = "KoeSnippetPrompt"
_W, _H = 310, 78
_AUTO_DISMISS_S = 5.0

# ── Win32 constants ────────────────────────────────────────────────────────
WS_POPUP         = 0x80000000
WS_VISIBLE       = 0x10000000
WS_EX_TOPMOST    = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_LAYERED    = 0x00080000

WM_DESTROY  = 0x0002
WM_PAINT    = 0x000F
WM_TIMER    = 0x0113
WM_KEYDOWN  = 0x0100
WM_HOTKEY   = 0x0312
WM_CLOSE    = 0x0010
WM_NCHITTEST = 0x0084
HTCLIENT     = 1

VK_TAB      = 0x09
VK_ESCAPE   = 0x1B

CS_HREDRAW  = 0x0002
CS_VREDRAW  = 0x0001

LWA_ALPHA   = 0x00000002
DT_LEFT     = 0x00000000
DT_SINGLELINE = 0x00000020
DT_VCENTER  = 0x00000004
DT_NOPREFIX = 0x00000800
DT_WORD_ELLIPSIS = 0x00040000
DT_END_ELLIPSIS  = 0x00008000

TRANSPARENT = 1
OPAQUE      = 2

# Colours (COLORREF = 0x00BBGGRR)
_C_BG      = 0x00100D0D   # #0D0D10
_C_BORDER  = 0x00252218   # #181822
_C_TEXT    = 0x00E1E6E8   # #E8E6E1
_C_SUB     = 0x00807A78   # #787A80
_C_HINT    = 0x00504C4A   # #4A4C50
_C_ACCENT  = 0x00D0A870   # #70A8D0  (blue-ish)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize",        ctypes.c_uint),
        ("style",         ctypes.c_uint),
        ("lpfnWndProc",   ctypes.c_void_p),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     ctypes.c_void_p),
        ("hIcon",         ctypes.c_void_p),
        ("hCursor",       ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName",  ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm",       ctypes.c_void_p),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc",          ctypes.c_void_p),
        ("fErase",       wt.BOOL),
        ("rcPaint",      wt.RECT),
        ("fRestore",     wt.BOOL),
        ("fIncUpdate",   wt.BOOL),
        ("rgbReserved",  ctypes.c_byte * 32),
    ]


class _LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight",         wt.LONG),
        ("lfWidth",          wt.LONG),
        ("lfEscapement",     wt.LONG),
        ("lfOrientation",    wt.LONG),
        ("lfWeight",         wt.LONG),
        ("lfItalic",         ctypes.c_byte),
        ("lfUnderline",      ctypes.c_byte),
        ("lfStrikeOut",      ctypes.c_byte),
        ("lfCharSet",        ctypes.c_byte),
        ("lfOutPrecision",   ctypes.c_byte),
        ("lfClipPrecision",  ctypes.c_byte),
        ("lfQuality",        ctypes.c_byte),
        ("lfPitchAndFamily", ctypes.c_byte),
        ("lfFaceName",       ctypes.c_wchar * 32),
    ]


def _make_logfont(size: int, bold: bool = False, face: str = "Segoe UI") -> _LOGFONTW:
    lf = _LOGFONTW()
    lf.lfHeight         = -size
    lf.lfWeight         = 700 if bold else 400
    lf.lfQuality        = 5   # CLEARTYPE_QUALITY
    lf.lfCharSet        = 0   # ANSI_CHARSET
    lf.lfFaceName       = face
    return lf


def _make_brush(color: int) -> ctypes.c_void_p:
    return ctypes.c_void_p(_gdi.CreateSolidBrush(color))


def _get_cursor_pos() -> tuple[int, int]:
    class _PT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = _PT()
    _u32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _screen_size() -> tuple[int, int]:
    return _u32.GetSystemMetrics(0), _u32.GetSystemMetrics(1)


# ── SnippetPrompt ──────────────────────────────────────────────────────────

class SnippetPrompt:
    """Floating Win32 window that offers inline snippet replacement."""

    _registered = False
    _wndproc_ref = None   # keep WNDPROC alive

    def __init__(self):
        self._lock    = threading.Lock()
        self._active  = False
        self._hwnd    = None
        self._ctx: dict | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    def offer(
        self,
        trigger: str,
        expansion: str,
        delivered_text: str,
        on_accept: Callable[[], None],
        on_dismiss: Callable[[], None],
    ) -> None:
        """Show the prompt near the mouse cursor. Non-blocking."""
        self.dismiss()
        with self._lock:
            self._active = True
            self._ctx = {
                "trigger":    trigger,
                "expansion":  expansion,
                "delivered":  delivered_text,
                "on_accept":  on_accept,
                "on_dismiss": on_dismiss,
            }
        threading.Thread(
            target=self._run,
            daemon=True,
            name="koe-snippet-prompt",
        ).start()

    def dismiss(self):
        """Programmatically dismiss any visible prompt."""
        with self._lock:
            self._active = False
            hwnd = self._hwnd
        if hwnd:
            try:
                _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

    # ── Window thread ──────────────────────────────────────────────────────

    def _run(self):
        with self._lock:
            ctx = self._ctx
        if ctx is None:
            return

        try:
            self._register_class()
            hwnd = self._create_window(ctx["trigger"], ctx["expansion"])
            if not hwnd:
                ctx["on_dismiss"]()
                return

            with self._lock:
                self._hwnd = hwnd

            # Timer for auto-dismiss (ID=1)
            _u32.SetTimer(hwnd, 1, int(_AUTO_DISMISS_S * 1000), None)

            # Message loop
            msg = ctypes.create_string_buffer(64)
            accepted = [False]
            _SnippetPrompt._active_map[hwnd] = (self, ctx, accepted)

            while _u32.GetMessageW(msg, hwnd, 0, 0) > 0:
                _u32.TranslateMessage(msg)
                _u32.DispatchMessageW(msg)

            _SnippetPrompt._active_map.pop(hwnd, None)

            with self._lock:
                self._hwnd = None

            if accepted[0]:
                ctx["on_accept"]()
            else:
                ctx["on_dismiss"]()

        except Exception:
            logger.exception("SnippetPrompt thread error")
            try:
                ctx["on_dismiss"]()
            except Exception:
                pass
        finally:
            with self._lock:
                self._active = False

    def _create_window(self, trigger: str, expansion: str) -> int:
        cx, cy = _get_cursor_pos()
        sw, sh = _screen_size()
        x = min(cx + 12, sw - _W - 12)
        y = min(cy + 24, sh - _H - 12)

        inst = _ker.GetModuleHandleW(None)
        hwnd = _u32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            _CLASS_NAME,
            "Koe Snippet",
            WS_POPUP | WS_VISIBLE,
            x, y, _W, _H,
            None, None, inst, None,
        )
        return hwnd

    # ── WndProc ────────────────────────────────────────────────────────────

    @staticmethod
    def _wnd_proc(hwnd, msg, wparam, lparam):
        entry = _SnippetPrompt._active_map.get(hwnd)
        if entry:
            self_ref, ctx, accepted = entry

            if msg == WM_PAINT:
                ps = _PAINTSTRUCT()
                hdc = _u32.BeginPaint(hwnd, ctypes.byref(ps))
                _SnippetPrompt._paint(hdc, ctx["trigger"], ctx["expansion"])
                _u32.EndPaint(hwnd, ctypes.byref(ps))
                return 0

            if msg == WM_TIMER and wparam == 1:
                _u32.KillTimer(hwnd, 1)
                _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return 0

            if msg == WM_KEYDOWN:
                if wparam == VK_TAB:
                    accepted[0] = True
                    _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                elif wparam == VK_ESCAPE:
                    _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return 0

            if msg == WM_NCHITTEST:
                return HTCLIENT   # make window receive keyboard (focus-less)

            if msg == WM_DESTROY:
                _u32.PostQuitMessage(0)
                return 0

        return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    @staticmethod
    def _paint(hdc, trigger: str, expansion: str):
        # Background
        bg_brush = _make_brush(_C_BG)
        rc = wt.RECT(0, 0, _W, _H)
        _u32.FillRect(hdc, ctypes.byref(rc), bg_brush)
        _gdi.DeleteObject(bg_brush)

        # Border (1px inside)
        border_pen = _gdi.CreatePen(0, 1, _C_BORDER)
        old_pen    = _gdi.SelectObject(hdc, border_pen)
        null_brush = _gdi.GetStockObject(5)  # NULL_BRUSH
        old_brush  = _gdi.SelectObject(hdc, null_brush)
        _gdi.Rectangle(hdc, 0, 0, _W, _H)
        _gdi.SelectObject(hdc, old_pen)
        _gdi.SelectObject(hdc, old_brush)
        _gdi.DeleteObject(border_pen)

        _gdi.SetBkMode(hdc, TRANSPARENT)

        # Line 1: trigger label
        font_bold = _gdi.CreateFontIndirectW(ctypes.byref(_make_logfont(11, bold=True)))
        old_font  = _gdi.SelectObject(hdc, font_bold)
        _gdi.SetTextColor(hdc, _C_TEXT)
        label = f'Replace "{trigger}"?'
        rc1 = wt.RECT(12, 10, _W - 12, 30)
        _u32.DrawTextW(hdc, label, len(label), ctypes.byref(rc1),
                       DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | DT_END_ELLIPSIS)
        _gdi.SelectObject(hdc, old_font)
        _gdi.DeleteObject(font_bold)

        # Line 2: expansion preview
        font_norm = _gdi.CreateFontIndirectW(ctypes.byref(_make_logfont(10)))
        _gdi.SelectObject(hdc, font_norm)
        _gdi.SetTextColor(hdc, _C_SUB)
        preview = (expansion[:42] + "…") if len(expansion) > 42 else expansion
        rc2 = wt.RECT(12, 32, _W - 12, 52)
        _u32.DrawTextW(hdc, preview, len(preview), ctypes.byref(rc2),
                       DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | DT_END_ELLIPSIS)

        # Line 3: hint
        _gdi.SetTextColor(hdc, _C_HINT)
        hint = "Tab = Replace   Esc = Skip"
        rc3 = wt.RECT(12, 54, _W - 12, _H - 4)
        _u32.DrawTextW(hdc, hint, len(hint), ctypes.byref(rc3),
                       DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

        _gdi.SelectObject(hdc, font_norm)
        _gdi.DeleteObject(font_norm)

    @classmethod
    def _register_class(cls):
        if cls._registered:
            return
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                     ctypes.c_uint, ctypes.c_ulong, ctypes.c_long)
        cls._wndproc_ref = WNDPROC(cls._wnd_proc)

        wc = _WNDCLASSEXW()
        wc.cbSize        = ctypes.sizeof(_WNDCLASSEXW)
        wc.style         = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc   = ctypes.cast(cls._wndproc_ref, ctypes.c_void_p).value
        wc.hInstance     = _ker.GetModuleHandleW(None)
        wc.lpszClassName = _CLASS_NAME
        _u32.RegisterClassExW(ctypes.byref(wc))
        cls._registered  = True


# Module-level map shared by the static WndProc
_SnippetPrompt = SnippetPrompt
_SnippetPrompt._active_map: dict = {}
