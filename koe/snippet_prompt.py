"""Floating prompt that appears near the cursor offering snippet expansion.

Win32 popup window (no tkinter — avoids forrtl/MKL thread conflicts).
Keyboard detection via keyboard.hook() so WS_EX_NOACTIVATE is safe.
The user can press Tab or click the window to accept, Esc to dismiss.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

_u32 = ctypes.windll.user32
_gdi = ctypes.windll.gdi32
_ker = ctypes.windll.kernel32

_CLASS_NAME      = "KoeSnippetPrompt"
_W, _H           = 320, 80
_AUTO_DISMISS_MS = 5000

# ── Win32 constants ────────────────────────────────────────────────────────
WS_POPUP         = 0x80000000
WS_VISIBLE       = 0x10000000
WS_EX_TOPMOST    = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

WM_DESTROY    = 0x0002
WM_CLOSE      = 0x0010
WM_PAINT      = 0x000F
WM_TIMER      = 0x0113
WM_LBUTTONDOWN = 0x0201

# User-defined messages (PostMessageW from keyboard hook → WndProc)
WM_KOE_ACCEPT  = 0x8001
WM_KOE_DISMISS = 0x8002

CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001

TRANSPARENT      = 1
DT_LEFT          = 0x00000000
DT_SINGLELINE    = 0x00000020
DT_VCENTER       = 0x00000004
DT_NOPREFIX      = 0x00000800
DT_END_ELLIPSIS  = 0x00008000

# Colours (COLORREF = 0x00BBGGRR)
_C_BG     = 0x00100D0D   # #0D0D10
_C_BORDER = 0x00252218   # #181822
_C_TEXT   = 0x00E1E6E8   # #E8E6E1
_C_SUB    = 0x00807A78   # #787A80
_C_HINT   = 0x00504C4A   # #4A4C50
_C_ACCENT = 0x00D0A870   # #70A8D0


# ── ctypes structs ─────────────────────────────────────────────────────────

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


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc",        ctypes.c_void_p),
        ("fErase",     wt.BOOL),
        ("rcPaint",    wt.RECT),
        ("fRestore",   wt.BOOL),
        ("fIncUpdate", wt.BOOL),
        ("rgbReserved",ctypes.c_byte * 32),
    ]


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
    lf.lfHeight  = -size
    lf.lfWeight  = 700 if bold else 400
    lf.lfQuality = 5   # CLEARTYPE_QUALITY
    lf.lfFaceName = face
    return lf


def _cursor_pos() -> tuple[int, int]:
    pt = wt.POINT()
    _u32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _screen_size() -> tuple[int, int]:
    return _u32.GetSystemMetrics(0), _u32.GetSystemMetrics(1)


# ── Module-level registry for WndProc ─────────────────────────────────────
# Maps hwnd (int) → {"accepted": bool}
_active: dict[int, dict] = {}
_wndproc_ref = None    # keep WNDPROC alive
_class_registered = False


def _register_class() -> None:
    global _class_registered, _wndproc_ref
    if _class_registered:
        return

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
    )
    _wndproc_ref = WNDPROC(_wnd_proc)

    wc               = _WNDCLASSEXW()
    wc.cbSize        = ctypes.sizeof(_WNDCLASSEXW)
    wc.style         = CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc   = ctypes.cast(_wndproc_ref, ctypes.c_void_p).value
    wc.hInstance     = _ker.GetModuleHandleW(None)
    wc.lpszClassName = _CLASS_NAME
    _u32.RegisterClassExW(ctypes.byref(wc))
    _class_registered = True


def _wnd_proc(hwnd, msg, wparam, lparam):
    ctx = _active.get(hwnd)

    if ctx is not None:
        if msg == WM_PAINT:
            ps  = _PAINTSTRUCT()
            hdc = _u32.BeginPaint(hwnd, ctypes.byref(ps))
            _paint(hdc, ctx["trigger"], ctx["expansion"])
            _u32.EndPaint(hwnd, ctypes.byref(ps))
            return 0

        if msg == WM_TIMER and wparam == 1:
            _u32.KillTimer(hwnd, 1)
            _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0

        if msg == WM_LBUTTONDOWN:
            ctx["accepted"] = True
            _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0

        if msg == WM_KOE_ACCEPT:
            ctx["accepted"] = True
            _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0

        if msg == WM_KOE_DISMISS:
            _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0

        if msg == WM_DESTROY:
            _u32.PostQuitMessage(0)
            return 0

    return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _paint(hdc, trigger: str, expansion: str) -> None:
    # Background
    bg = _gdi.CreateSolidBrush(_C_BG)
    rc = wt.RECT(0, 0, _W, _H)
    _u32.FillRect(hdc, ctypes.byref(rc), bg)
    _gdi.DeleteObject(bg)

    # Border
    pen  = _gdi.CreatePen(0, 1, _C_BORDER)
    oldp = _gdi.SelectObject(hdc, pen)
    null = _gdi.GetStockObject(5)   # NULL_BRUSH
    oldb = _gdi.SelectObject(hdc, null)
    _gdi.Rectangle(hdc, 0, 0, _W, _H)
    _gdi.SelectObject(hdc, oldp)
    _gdi.SelectObject(hdc, oldb)
    _gdi.DeleteObject(pen)

    _gdi.SetBkMode(hdc, TRANSPARENT)

    # Line 1 — headline
    fb  = _gdi.CreateFontIndirectW(ctypes.byref(_make_logfont(11, bold=True)))
    old = _gdi.SelectObject(hdc, fb)
    _gdi.SetTextColor(hdc, _C_TEXT)
    label = f'Replace "{trigger}"?'
    r1 = wt.RECT(12, 9, _W - 12, 29)
    _u32.DrawTextW(hdc, label, len(label), ctypes.byref(r1),
                   DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | DT_END_ELLIPSIS)
    _gdi.SelectObject(hdc, old)
    _gdi.DeleteObject(fb)

    fn  = _gdi.CreateFontIndirectW(ctypes.byref(_make_logfont(10)))
    old = _gdi.SelectObject(hdc, fn)

    # Line 2 — expansion preview
    _gdi.SetTextColor(hdc, _C_SUB)
    preview = (expansion[:44] + "…") if len(expansion) > 44 else expansion
    r2 = wt.RECT(12, 31, _W - 12, 53)
    _u32.DrawTextW(hdc, preview, len(preview), ctypes.byref(r2),
                   DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | DT_END_ELLIPSIS)

    # Line 3 — hint
    _gdi.SetTextColor(hdc, _C_HINT)
    hint = "Tab or click = Replace   Esc = Skip"
    r3 = wt.RECT(12, 55, _W - 12, _H - 4)
    _u32.DrawTextW(hdc, hint, len(hint), ctypes.byref(r3),
                   DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

    _gdi.SelectObject(hdc, old)
    _gdi.DeleteObject(fn)


# ── SnippetPrompt ──────────────────────────────────────────────────────────

class SnippetPrompt:
    """Floating Win32 window that offers inline snippet replacement."""

    def __init__(self):
        self._lock  = threading.Lock()
        self._hwnd: int | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    def offer(
        self,
        trigger:        str,
        expansion:      str,
        delivered_text: str,
        on_accept:      Callable[[], None],
        on_dismiss:     Callable[[], None],
    ) -> None:
        """Show the prompt near the mouse cursor. Non-blocking."""
        self.dismiss()
        threading.Thread(
            target=self._run,
            args=(trigger, expansion, delivered_text, on_accept, on_dismiss),
            daemon=True,
            name="koe-snippet-prompt",
        ).start()

    def dismiss(self) -> None:
        """Programmatically close any visible prompt."""
        with self._lock:
            hwnd = self._hwnd
        if hwnd:
            try:
                _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

    # ── Window thread ──────────────────────────────────────────────────────

    def _run(self, trigger, expansion, delivered_text, on_accept, on_dismiss):
        try:
            import keyboard as _kb
        except ImportError:
            logger.warning("keyboard library missing — snippet prompt disabled")
            on_dismiss()
            return

        hwnd = None
        hook_ref = None
        try:
            _register_class()

            # Create window
            cx, cy = _cursor_pos()
            sw, sh = _screen_size()
            x = min(cx + 14, sw - _W - 14)
            y = min(cy + 26, sh - _H - 14)
            inst = _ker.GetModuleHandleW(None)
            hwnd = _u32.CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                _CLASS_NAME, "Koe",
                WS_POPUP | WS_VISIBLE,
                x, y, _W, _H,
                None, None, inst, None,
            )
            if not hwnd:
                on_dismiss()
                return

            with self._lock:
                self._hwnd = hwnd

            ctx = {"trigger": trigger, "expansion": expansion, "accepted": False}
            _active[hwnd] = ctx

            # Auto-dismiss timer
            _u32.SetTimer(hwnd, 1, _AUTO_DISMISS_MS, None)

            # Global keyboard hook — posts user messages to hwnd (thread-safe)
            def _on_key(ev):
                if ev.event_type != "down":
                    return
                if ev.name == "tab":
                    _u32.PostMessageW(hwnd, WM_KOE_ACCEPT, 0, 0)
                elif ev.name == "esc":
                    _u32.PostMessageW(hwnd, WM_KOE_DISMISS, 0, 0)

            hook_ref = _kb.hook(_on_key, suppress=False)

            # Message loop
            msg = _MSG()
            while _u32.GetMessageW(ctypes.byref(msg), hwnd, 0, 0) > 0:
                _u32.TranslateMessage(ctypes.byref(msg))
                _u32.DispatchMessageW(ctypes.byref(msg))

            accepted = ctx.get("accepted", False)

        except Exception:
            logger.exception("SnippetPrompt thread error")
            accepted = False
        finally:
            if hook_ref is not None:
                try:
                    import keyboard as _kb
                    _kb.unhook(hook_ref)
                except Exception:
                    pass
            if hwnd is not None:
                _active.pop(hwnd, None)
                with self._lock:
                    if self._hwnd == hwnd:
                        self._hwnd = None

        if accepted:
            try:
                on_accept()
            except Exception:
                logger.exception("snippet on_accept error")
        else:
            try:
                on_dismiss()
            except Exception:
                pass
