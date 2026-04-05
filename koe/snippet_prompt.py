"""Floating prompt that appears near the cursor offering snippet expansion.

Uses tkinter (stdlib) positioned near the mouse cursor. Shown after Koe
delivers text that contains a snippet trigger. The user can press Tab to
accept (replace text + expand) or Esc / click Skip to dismiss.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from typing import Callable

logger = logging.getLogger(__name__)

_AUTO_DISMISS_MS = 5000
_W, _H = 340, 88


class SnippetPrompt:
    """Floating tkinter window that offers inline snippet replacement."""

    def __init__(self):
        self._lock         = threading.Lock()
        self._active       = False
        self._dismiss_ev:  threading.Event | None = None
        self._accept_flag  = False

    # ── Public API ─────────────────────────────────────────────────────────

    def offer(
        self,
        trigger:       str,
        expansion:     str,
        delivered_text: str,
        on_accept:     Callable[[], None],
        on_dismiss:    Callable[[], None],
    ) -> None:
        """Show the prompt near the mouse cursor. Non-blocking."""
        self.dismiss()          # close any existing prompt first
        with self._lock:
            self._active = True
        threading.Thread(
            target=self._run,
            args=(trigger, expansion, delivered_text, on_accept, on_dismiss),
            daemon=True,
            name="koe-snippet-prompt",
        ).start()

    def dismiss(self) -> None:
        """Programmatically dismiss any visible prompt."""
        with self._lock:
            self._active = False
            ev = self._dismiss_ev
        if ev:
            ev.set()

    # ── Window thread ──────────────────────────────────────────────────────

    def _run(self, trigger, expansion, delivered_text, on_accept, on_dismiss):
        try:
            import keyboard as _kb
        except ImportError:
            logger.warning("keyboard library not available — snippet prompt disabled")
            on_dismiss()
            return

        dismiss_ev = threading.Event()
        with self._lock:
            self._dismiss_ev  = dismiss_ev
            self._accept_flag = False

        root = None
        hook_ref = None
        try:
            root = tk.Tk()
            root.overrideredirect(True)
            root.wm_attributes("-topmost", True)
            root.wm_attributes("-alpha",   0.97)

            # ── Position near cursor (tkinter logical coords) ──────────
            cx, cy = root.winfo_pointerxy()
            sw     = root.winfo_screenwidth()
            sh     = root.winfo_screenheight()
            x = min(cx + 14, sw - _W - 14)
            y = min(cy + 26, sh - _H - 14)
            root.geometry(f"{_W}x{_H}+{x}+{y}")
            root.configure(bg="#181822")   # border colour

            # ── Inner frame ────────────────────────────────────────────
            inner = tk.Frame(root, bg="#0D0D10", padx=13, pady=10)
            inner.pack(fill="both", expand=True, padx=1, pady=1)

            # Row 1 — headline
            title = f'Replace "{trigger}"?'
            tk.Label(
                inner, text=title, bg="#0D0D10", fg="#E8E6E1",
                font=("Segoe UI", 10, "bold"), anchor="w",
            ).pack(fill="x")

            # Row 2 — expansion preview
            preview = (expansion[:54] + "…") if len(expansion) > 54 else expansion
            tk.Label(
                inner, text=preview, bg="#0D0D10", fg="#787A80",
                font=("Segoe UI", 9), anchor="w",
            ).pack(fill="x", pady=(3, 0))

            # Row 3 — hint + button
            hint_row = tk.Frame(inner, bg="#0D0D10")
            hint_row.pack(fill="x", pady=(8, 0))

            tk.Label(
                hint_row, text="Tab = Replace   Esc = Skip",
                bg="#0D0D10", fg="#4A4C50",
                font=("Segoe UI", 8), anchor="w",
            ).pack(side="left")

            # ── Accept / dismiss callbacks ──────────────────────────────
            def _accept(_event=None):
                with self._lock:
                    self._accept_flag = True
                dismiss_ev.set()

            def _skip(_event=None):
                dismiss_ev.set()

            replace_btn = tk.Label(
                hint_row, text="Replace →",
                bg="#1A1E30", fg="#70A8D0",
                font=("Segoe UI", 8, "bold"), padx=8, pady=3,
                cursor="hand2",
            )
            replace_btn.pack(side="right")
            replace_btn.bind("<Button-1>", _accept)
            replace_btn.bind("<Enter>", lambda e: replace_btn.configure(bg="#252A42"))
            replace_btn.bind("<Leave>", lambda e: replace_btn.configure(bg="#1A1E30"))

            # ── Global keyboard hook (Tab / Esc) ───────────────────────
            def _on_key(ev):
                if ev.event_type != "down":
                    return
                if ev.name == "tab":
                    _accept()
                elif ev.name == "esc":
                    _skip()

            hook_ref = _kb.hook(_on_key, suppress=False)

            # ── Auto-dismiss ───────────────────────────────────────────
            root.after(_AUTO_DISMISS_MS, _skip)

            # ── Poll dismiss_ev every 50 ms from tkinter loop ──────────
            def _poll():
                if dismiss_ev.is_set():
                    try:
                        root.destroy()
                    except Exception:
                        pass
                    return
                root.after(50, _poll)

            root.after(50, _poll)
            root.mainloop()

        except Exception:
            logger.exception("SnippetPrompt thread error")
        finally:
            # Unhook keyboard
            if hook_ref is not None:
                try:
                    import keyboard as _kb
                    _kb.unhook(hook_ref)
                except Exception:
                    pass
            # Fire callback
            with self._lock:
                self._active      = False
                accepted          = self._accept_flag
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
