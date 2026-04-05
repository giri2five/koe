"""Koe app and tray icons — uses the Koe_logo.png asset."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

_ASSETS = Path(__file__).resolve().parent / "assets"
_LOGO_PATH = _ASSETS / "koe_logo.png"

# Red recording-dot colour
_REC_DOT = (220, 50, 50, 230)


def _load_logo(size: int) -> Image.Image:
    """Load the logo PNG and resize to *size* × *size* with high quality."""
    img = Image.open(_LOGO_PATH).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    return img


def _add_recording_dot(img: Image.Image) -> Image.Image:
    """Overlay a red dot in the top-right corner (recording indicator)."""
    img = img.copy()
    draw = ImageDraw.Draw(img)
    size = img.width
    s = size / 32.0
    dot_r = max(2, round(3 * s))
    dot_x = size - dot_r - max(1, round(1.5 * s))
    dot_y = dot_r + max(1, round(1.5 * s))
    draw.ellipse(
        [dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r],
        fill=_REC_DOT,
    )
    return img


def _dim(img: Image.Image, alpha: int = 140) -> Image.Image:
    """Return a dimmed copy of *img* (used for error / idle states)."""
    img = img.copy()
    r, g, b, a = img.split()
    a = a.point(lambda v: int(v * alpha / 255))
    return Image.merge("RGBA", (r, g, b, a))


def create_icon(state: str = "idle", size: int = 32) -> Image.Image:
    """Return a PIL RGBA icon for *state* at *size* × *size* pixels."""
    base = _load_logo(size)
    if state == "recording":
        return _add_recording_dot(base)
    if state == "processing":
        return base   # full brightness while processing
    if state == "error":
        return _dim(base, 120)
    return base   # idle


# Pre-built instances (32 px — used for tray)
ICON_IDLE       = create_icon("idle")
ICON_RECORDING  = create_icon("recording")
ICON_PROCESSING = create_icon("processing")
ICON_ERROR      = create_icon("error")


def get_icon(state: str) -> Image.Image:
    """Return the pre-generated tray icon for a state."""
    return {
        "idle":       ICON_IDLE,
        "recording":  ICON_RECORDING,
        "processing": ICON_PROCESSING,
        "error":      ICON_ERROR,
    }.get(state, ICON_IDLE)


def get_app_icon(state: str = "idle", size: int = 64):
    """Return a Tk-compatible app icon image."""
    from PIL import ImageTk
    return ImageTk.PhotoImage(create_icon(state, size=size))


def ensure_icon_file() -> Path:
    """Ensure a fresh ICO file exists for the desktop shell (always regenerated)."""
    icon_path = _ASSETS / "koe.ico"

    # Build multi-size ICO from the logo PNG (always regenerated so updates take effect).
    sizes = [256, 128, 64, 32, 16]
    images = [_load_logo(s) for s in sizes]
    images[0].save(
        icon_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    return icon_path
