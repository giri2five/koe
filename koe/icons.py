"""Programmatic Koe app and tray icons."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageTk


STATE_COLORS = {
    "idle": ("#F1EFE9", "#CFCBC4"),
    "recording": ("#FFFFFF", "#E8E4DD"),
    "processing": ("#E8D6B9", "#D9B37A"),
    "error": ("#C3B8B3", "#8C7F79"),
}


def create_icon(state: str = "idle", size: int = 32) -> Image.Image:
    """Create a rounded Koe glyph icon for tray usage."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    outer = [2, 2, size - 2, size - 2]
    radius = max(6, size // 4)
    draw.rounded_rectangle(outer, radius=radius, fill="#17171A")
    draw.rounded_rectangle([3, 3, size - 3, size - 3], radius=max(5, radius - 2), outline="#303036", width=1)

    base, inner = STATE_COLORS.get(state, STATE_COLORS["idle"])
    inset = max(7, size // 4)
    cx = size // 2
    cy = size // 2
    diamond = [
        (cx, inset - 1),
        (size - inset + 1, cy),
        (cx, size - inset + 1),
        (inset - 1, cy),
    ]
    draw.polygon(diamond, fill=base)

    inner_inset = inset + max(4, size // 10)
    inner_diamond = [
        (cx, inner_inset),
        (size - inner_inset, cy),
        (cx, size - inner_inset),
        (inner_inset, cy),
    ]
    draw.polygon(inner_diamond, fill=inner)
    dot = max(4, size // 8)
    draw.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill="#FFFFFF")
    return img


ICON_IDLE = create_icon("idle")
ICON_RECORDING = create_icon("recording")
ICON_PROCESSING = create_icon("processing")
ICON_ERROR = create_icon("error")


def get_icon(state: str) -> Image.Image:
    """Return the pre-generated tray icon for a state."""
    icons = {
        "idle": ICON_IDLE,
        "recording": ICON_RECORDING,
        "processing": ICON_PROCESSING,
        "error": ICON_ERROR,
    }
    return icons.get(state, ICON_IDLE)


def get_app_icon(state: str = "idle", size: int = 64):
    """Return a Tk-compatible app icon image."""
    return ImageTk.PhotoImage(create_icon(state, size=size))


def ensure_icon_file() -> Path:
    """Ensure a real ICO file exists for the desktop shell."""
    asset_dir = Path(__file__).resolve().parent / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    icon_path = asset_dir / "koe.ico"
    if not icon_path.exists():
        image = create_icon("idle", size=256)
        image.save(icon_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    return icon_path
