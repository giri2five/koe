"""Minimal live overlay capsule for Koe."""

from __future__ import annotations

import logging
import math
import threading
from enum import Enum
from typing import Callable

import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from System import Action
from System import IntPtr
from System.Drawing import Color, Pen, Rectangle, Region, SolidBrush
from System.Drawing.Drawing2D import GraphicsPath, LinearGradientBrush, SmoothingMode
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import (
    Application,
    ControlStyles,
    Form,
    FormBorderStyle,
    FormStartPosition,
    Screen,
    Timer,
)

logger = logging.getLogger(__name__)


class OverlayState(Enum):
    """Visibility state for the live overlay."""

    HIDDEN = "hidden"
    RECORDING = "recording"
    PROCESSING = "processing"


LISTENING_SIZE = (138, 40)
PROCESSING_SIZE = (132, 36)
TOP_MARGIN = 18
SURFACE_OUTER = Color.FromArgb(232, 7, 7, 9)
SURFACE_INNER_TOP = Color.FromArgb(228, 22, 22, 24)
SURFACE_INNER_BOTTOM = Color.FromArgb(220, 10, 10, 12)
BORDER = Color.FromArgb(24, 255, 255, 255)
SHADOW = Color.FromArgb(76, 0, 0, 0)
BAR_BRIGHT = Color.FromArgb(246, 246, 242)
BAR_SOFT = Color.FromArgb(134, 134, 140)
DOT_SOFT = Color.FromArgb(84, 84, 90)
GLOW_OUTER = Color.FromArgb(34, 255, 255, 255)
GLOW_INNER = Color.FromArgb(228, 255, 255, 255)
TRANSPARENT_KEY = Color.FromArgb(1, 1, 1)


class _OverlayForm(Form):
    """Borderless top-most overlay pill."""

    def __init__(self, owner: "Overlay"):
        super().__init__()
        self._owner = owner
        self.FormBorderStyle = getattr(FormBorderStyle, "None")
        self.StartPosition = FormStartPosition.Manual
        self.ShowInTaskbar = False
        self.TopMost = True
        self.BackColor = TRANSPARENT_KEY
        self.TransparencyKey = TRANSPARENT_KEY
        self.Width = LISTENING_SIZE[0]
        self.Height = LISTENING_SIZE[1]
        self.Opacity = 0.0

        self.SetStyle(
            ControlStyles.AllPaintingInWmPaint
            | ControlStyles.UserPaint
            | ControlStyles.OptimizedDoubleBuffer
            | ControlStyles.ResizeRedraw,
            True,
        )
        self.Paint += self._paint_overlay

    @property
    def ShowWithoutActivation(self):  # type: ignore[override]
        return True

    @property
    def CreateParams(self):  # type: ignore[override]
        params = super().CreateParams
        params.ExStyle |= 0x00000080  # WS_EX_TOOLWINDOW
        params.ExStyle |= 0x08000000  # WS_EX_NOACTIVATE
        params.ExStyle |= 0x00000020  # WS_EX_TRANSPARENT
        return params

    def _paint_overlay(self, sender, event):
        graphics = event.Graphics
        graphics.SmoothingMode = SmoothingMode.AntiAlias
        graphics.Clear(TRANSPARENT_KEY)

        width = self.Width
        height = self.Height

        outer_rect = Rectangle(3, 3, width - 6, height - 6)
        inner_rect = Rectangle(4, 4, width - 8, height - 8)
        shadow_rect = Rectangle(7, 10, width - 14, height - 14)

        shadow_path = _rounded_path(shadow_rect, max(12, shadow_rect.Height // 2))
        graphics.FillPath(SolidBrush(SHADOW), shadow_path)

        outer_path = _rounded_path(outer_rect, outer_rect.Height // 2)
        inner_path = _rounded_path(inner_rect, inner_rect.Height // 2)
        graphics.FillPath(SolidBrush(SURFACE_OUTER), outer_path)
        graphics.DrawPath(Pen(BORDER, 1), outer_path)

        gradient = LinearGradientBrush(
            inner_rect,
            SURFACE_INNER_TOP,
            SURFACE_INNER_BOTTOM,
            90.0,
        )
        graphics.FillPath(gradient, inner_path)

        center_x = width // 2
        center_y = height // 2
        glow_w = 40 if self._owner.state == OverlayState.RECORDING else 34
        glow_h = 14 if self._owner.state == OverlayState.RECORDING else 12
        graphics.FillEllipse(
            SolidBrush(GLOW_OUTER),
            center_x - glow_w // 2,
            center_y - glow_h // 2,
            glow_w,
            glow_h,
        )
        graphics.FillEllipse(
            SolidBrush(Color.FromArgb(30, 255, 255, 255)),
            center_x - 12,
            center_y - 4,
            24,
            8,
        )

        if self._owner.state == OverlayState.RECORDING:
            self._draw_bars(graphics, center_x, center_y)
        elif self._owner.state == OverlayState.PROCESSING:
            self._draw_dots(graphics, center_x, center_y)

    def _draw_bars(self, graphics, cx: int, cy: int):
        amplitude = self._owner._smoothed_rms
        heights = [6, 9, 13, 18, 22, 18, 13, 9, 6]
        start_x = cx - 20
        for index, base_height in enumerate(heights):
            pulse = 0.82 + 0.18 * math.sin(self._owner._phase * 2.5 + index * 0.58)
            height = max(4, base_height * max(0.16, amplitude) * pulse)
            x = start_x + index * 5
            y = int(cy - height / 2)
            brush = SolidBrush(BAR_BRIGHT if 2 <= index <= 6 else BAR_SOFT)
            _fill_rounded_rectangle(graphics, brush, x, y, 3, int(height), 2)

    def _draw_dots(self, graphics, cx: int, cy: int):
        active = int((self._owner._phase * 1.8) % 3)
        start_x = cx - 11
        for index in range(3):
            brush = SolidBrush(BAR_BRIGHT if index == active else DOT_SOFT)
            graphics.FillEllipse(brush, start_x + index * 11, cy - 3, 6, 6)

    def OnShown(self, event):  # type: ignore[override]
        self._sync_region()
        super().OnShown(event)

    def OnResize(self, event):  # type: ignore[override]
        self._sync_region()
        super().OnResize(event)

    def _sync_region(self):
        rect = Rectangle(2, 2, max(1, self.Width - 4), max(1, self.Height - 4))
        self.Region = Region(_rounded_path(rect, max(10, rect.Height // 2)))


class Overlay:
    """Small top-center capsule used while recording and processing."""

    def __init__(self, position: str = "bottom-right", hotkey_hint: str = "ALT + K"):
        self._position = position
        self._hotkey_hint = hotkey_hint
        self._state = OverlayState.HIDDEN
        self._target_state = OverlayState.HIDDEN
        self._phase = 0.0
        self._smoothed_rms = 0.24
        self._thread: Thread | None = None
        self._running = False
        self._form: _OverlayForm | None = None
        self._timer: Timer | None = None
        self.rms_source: Callable[[], float] | None = None
        self._lock = threading.Lock()
        self._current_bounds = [0.0, 0.0, float(LISTENING_SIZE[0]), float(LISTENING_SIZE[1])]
        self._current_opacity = 0.0

    def start(self):
        """Start the overlay UI thread."""
        if self._running:
            return
        self._running = True
        self._thread = Thread(ThreadStart(self._run))
        self._thread.SetApartmentState(ApartmentState.STA)
        self._thread.IsBackground = True
        self._thread.Start()

    def stop(self):
        """Stop the overlay UI thread."""
        self._running = False
        if self._form is not None:
            try:
                self._form.BeginInvoke(Action(self._form.Close))
            except Exception:
                logger.debug("Overlay close skipped", exc_info=True)

    def set_state(self, state: OverlayState):
        """Request a new visible state."""
        with self._lock:
            self._target_state = state

    @property
    def state(self) -> OverlayState:
        """Return the currently visible state."""
        return self._state

    def _run(self):
        try:
            self._form = _OverlayForm(self)
            tx, ty, tw, th, _ = self._target_bounds()
            self._current_bounds = [tx, ty - 12, float(tw), float(th)]
            self._form.Left = int(self._current_bounds[0])
            self._form.Top = int(self._current_bounds[1])
            self._form.Width = int(self._current_bounds[2])
            self._form.Height = int(self._current_bounds[3])

            self._timer = Timer()
            self._timer.Interval = 33
            self._timer.Tick += self._tick
            self._timer.Start()

            Application.Run(self._form)
        except Exception as exc:
            logger.error("Overlay failed: %s", exc, exc_info=True)

    def _tick(self, sender, event):
        if not self._running or self._form is None:
            if self._timer is not None:
                self._timer.Stop()
            if self._form is not None:
                self._form.Close()
            return

        self._phase += 0.15
        with self._lock:
            self._state = self._target_state
        self._smoothed_rms += (self._target_rms() - self._smoothed_rms) * 0.28

        tx, ty, tw, th, target_opacity = self._target_bounds()
        self._animate_bounds(tx, ty, tw, th, target_opacity)

        if self._current_opacity <= 0.01:
            if self._form.Visible:
                self._form.Hide()
            return

        self._form.SetBounds(
            int(self._current_bounds[0]),
            int(self._current_bounds[1]),
            int(self._current_bounds[2]),
            int(self._current_bounds[3]),
        )
        self._form.Opacity = max(0.0, min(1.0, self._current_opacity))

        if not self._form.Visible:
            self._form.Show()
        self._form.Invalidate()

    def _target_bounds(self) -> tuple[float, float, float, float, float]:
        bounds = self._active_screen_bounds()
        if self._state == OverlayState.PROCESSING:
            width, height = PROCESSING_SIZE
        else:
            width, height = LISTENING_SIZE

        x = bounds.Left + (bounds.Width - width) / 2
        base_y = bounds.Top + TOP_MARGIN

        if self._state == OverlayState.HIDDEN:
            return x, base_y - 12, width, height, 0.0

        return x, base_y, width, height, 1.0

    def _active_screen_bounds(self):
        """Use a stable primary-screen anchor for the top-center capsule."""
        return Screen.PrimaryScreen.WorkingArea

    def _animate_bounds(self, tx: float, ty: float, tw: float, th: float, target_opacity: float):
        lerp = 0.28
        self._current_bounds[0] += (tx - self._current_bounds[0]) * lerp
        self._current_bounds[1] += (ty - self._current_bounds[1]) * lerp
        self._current_bounds[2] += (tw - self._current_bounds[2]) * lerp
        self._current_bounds[3] += (th - self._current_bounds[3]) * lerp
        self._current_opacity += (target_opacity - self._current_opacity) * 0.26

    def _get_rms(self) -> float:
        if self.rms_source is None:
            return 0.0
        try:
            return float(self.rms_source())
        except Exception:
            return 0.0

    def _target_rms(self) -> float:
        return max(0.14, min(1.0, self._get_rms() * 11))


def _rounded_path(rect: Rectangle, radius: int) -> GraphicsPath:
    diameter = radius * 2
    path = GraphicsPath()
    path.AddArc(rect.X, rect.Y, diameter, diameter, 180, 90)
    path.AddArc(rect.Right - diameter, rect.Y, diameter, diameter, 270, 90)
    path.AddArc(rect.Right - diameter, rect.Bottom - diameter, diameter, diameter, 0, 90)
    path.AddArc(rect.X, rect.Bottom - diameter, diameter, diameter, 90, 90)
    path.CloseFigure()
    return path


def _fill_rounded_rectangle(graphics, brush, x: int, y: int, width: int, height: int, radius: int):
    rect = Rectangle(x, y, width, height)
    graphics.FillPath(brush, _rounded_path(rect, radius))
