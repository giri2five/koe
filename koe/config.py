"""Configuration management for Koe.

Loads from ~/.koe/config.toml with sensible defaults.
Creates default config on first run.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w


KOE_DIR = Path.home() / ".koe"
CONFIG_PATH = KOE_DIR / "config.toml"
MODELS_DIR = KOE_DIR / "models"


@dataclass
class HotkeyConfig:
    trigger: str = "alt+k"
    clipboard_toggle: str = ""


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    silence_threshold: float = 0.01
    device: str = "system_default"
    output_device: str = "system_default"
    # Minimum recording duration in seconds (ignore accidental taps)
    min_duration: float = 0.3
    # Maximum recording duration in seconds (safety limit)
    max_duration: float = 120.0


@dataclass
class TranscriptionConfig:
    model: str = "small.en"
    language: str = "en"
    device: str = "cuda"
    compute_type: str = "int8_float16"
    # beam_size: lower = faster, higher = more accurate
    beam_size: int = 5


@dataclass
class CleanupConfig:
    enabled: bool = True
    mode: str = "rules"  # "rules" or "llm"
    remove_fillers: bool = True
    fix_punctuation: bool = True
    fix_grammar: bool = True
    preserve_style: bool = True


@dataclass
class OutputConfig:
    default_mode: str = "both"  # "both", "type", or "clipboard"
    typing_speed: int = 0  # ms between keystrokes, 0 = instant


@dataclass
class UIConfig:
    show_overlay: bool = True
    overlay_position: str = "top-center"
    sound_feedback: bool = True


@dataclass
class KoeConfig:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def _dataclass_to_dict(obj) -> dict:
    """Convert nested dataclass to dict for TOML serialization."""
    result = {}
    for f in obj.__dataclass_fields__:
        val = getattr(obj, f)
        if hasattr(val, "__dataclass_fields__"):
            result[f] = _dataclass_to_dict(val)
        else:
            result[f] = val
    return result


def _update_dataclass(obj, data: dict):
    """Update dataclass fields from a dict, ignoring unknown keys."""
    for key, val in data.items():
        if hasattr(obj, key):
            current = getattr(obj, key)
            if hasattr(current, "__dataclass_fields__") and isinstance(val, dict):
                _update_dataclass(current, val)
            else:
                setattr(obj, key, val)


def load_config() -> KoeConfig:
    """Load config from disk, creating defaults if needed."""
    config = KoeConfig()

    KOE_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            data = tomllib.loads(f.read())
        _update_dataclass(config, data)
    else:
        save_config(config)

    return config


def save_config(config: KoeConfig):
    """Write config to disk."""
    KOE_DIR.mkdir(parents=True, exist_ok=True)
    data = _dataclass_to_dict(config)
    with open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(tomli_w.dumps(data))
