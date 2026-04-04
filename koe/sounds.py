"""Sound feedback for Koe.

Generates and plays subtle audio cues for recording start/stop/delivery.
All sounds are generated programmatically as numpy arrays — no external files.
"""

import logging
import numpy as np
import sounddevice as sd

from koe.devices import resolve_device

logger = logging.getLogger(__name__)

# Sample rate for all sounds
_SR = 44100
_OUTPUT_DEVICE: str | None = None


def _make_tone(freq: float, duration: float, volume: float = 0.15) -> np.ndarray:
    """Generate a sine tone with exponential decay envelope."""
    n_samples = int(_SR * duration)
    t = np.linspace(0, duration, n_samples, endpoint=False)
    # Exponential decay — fast attack, smooth tail
    envelope = np.exp(-t * (30 / duration))
    # Tiny linear attack to avoid click (5ms)
    attack_samples = min(int(_SR * 0.005), n_samples)
    envelope[:attack_samples] *= np.linspace(0, 1, attack_samples)
    signal = volume * np.sin(2 * np.pi * freq * t) * envelope
    return signal.astype(np.float32)


def _make_noise_tick(duration: float = 0.02, volume: float = 0.05) -> np.ndarray:
    """Generate a very soft noise tick for delivery confirmation."""
    n_samples = int(_SR * duration)
    envelope = np.exp(-np.linspace(0, 8, n_samples))
    noise = np.random.randn(n_samples).astype(np.float32)
    signal = volume * noise * envelope
    return signal.astype(np.float32)


# Pre-generated sounds (cached on module import)
# Start: warm blip at A5 (880Hz), 80ms
SOUND_START = _make_tone(freq=880, duration=0.08, volume=0.12)

# Stop: descending two-tone (E5 → A4), feels like "done"
SOUND_STOP = np.concatenate([
    _make_tone(freq=660, duration=0.04, volume=0.10),
    _make_tone(freq=440, duration=0.06, volume=0.10),
])

# Delivery: barely-audible tick
SOUND_DELIVER = _make_noise_tick(duration=0.02, volume=0.04)


def play(sound: np.ndarray):
    """Play a sound non-blocking. Silently fails if audio device is busy."""
    try:
        sd.play(
            sound,
            samplerate=_SR,
            blocking=False,
            device=resolve_device(_OUTPUT_DEVICE, "output"),
        )
    except Exception as e:
        logger.debug(f"Sound playback failed (non-critical): {e}")


def set_output_device(device: str | None):
    """Set the preferred playback device for feedback sounds."""
    global _OUTPUT_DEVICE
    _OUTPUT_DEVICE = device


def play_start():
    """Play the recording-start blip."""
    play(SOUND_START)


def play_stop():
    """Play the recording-stop tone."""
    play(SOUND_STOP)


def play_deliver():
    """Play the delivery confirmation tick."""
    play(SOUND_DELIVER)
