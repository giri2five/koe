"""Audio capture for Koe.

Records audio from the microphone into a numpy buffer while the hotkey is held.
Uses sounddevice (PortAudio backend) for reliable Windows audio capture.
"""

import logging
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd

from koe.config import AudioConfig
from koe.devices import resolve_device

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Records audio from microphone into a buffer.

    Usage:
        recorder = AudioRecorder(config)
        recorder.start()    # begin recording
        recorder.stop()     # stop and get audio
        audio = recorder.get_audio()  # numpy array, float32, mono, 16kHz
    """

    def __init__(self, config: AudioConfig):
        self.config = config
        self._sample_rate = config.sample_rate
        self._stream_sample_rate = float(config.sample_rate)
        self._chunks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._recording = False
        self._start_time = 0.0
        self._lock = threading.Lock()
        self._current_rms = 0.0  # Real-time RMS for waveform overlay
        self._active_device_name = "Unknown"

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice for each audio chunk."""
        if status:
            logger.warning(f"Audio status: {status}")
        if self._recording:
            mono = indata[:, 0] if indata.ndim == 2 else indata
            with self._lock:
                self._chunks.append(np.asarray(mono, dtype=np.float32).copy())
            # Update RMS for waveform visualization (atomic float write, no lock needed)
            self._current_rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float64)))

    def _resolve_input_device(self) -> int | str | None:
        """Pick a usable input device, preferring the configured one."""
        try:
            devices = sd.query_devices()
        except Exception as exc:
            raise RuntimeError("Unable to query audio devices.") from exc

        if isinstance(self.config.device, str):
            choice = self.config.device.strip()
            if choice and choice not in {"system_default", "default"}:
                exact_matches: list[tuple[int, dict]] = []
                fuzzy_matches: list[tuple[int, dict]] = []
                wanted = choice.casefold()
                for index, device in enumerate(devices):
                    if device.get("max_input_channels", 0) <= 0:
                        continue
                    name = str(device.get("name", "")).strip()
                    if not name:
                        continue
                    if name.casefold() == wanted:
                        exact_matches.append((index, dict(device)))
                    elif wanted in name.casefold():
                        fuzzy_matches.append((index, dict(device)))

                candidates = exact_matches or fuzzy_matches
                if candidates:
                    best_index, best_device = min(
                        candidates,
                        key=lambda item: (
                            abs(float(item[1].get("default_samplerate", 0)) - self._sample_rate),
                            -int(item[1].get("max_input_channels", 0)),
                            item[0],
                        ),
                    )
                    logger.info(
                        "Using preferred input device: %s (index=%s, default_sr=%s)",
                        best_device.get("name", best_index),
                        best_index,
                        best_device.get("default_samplerate"),
                    )
                    return best_index

        resolved = resolve_device(self.config.device, "input")
        if resolved is not None:
            return resolved

        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) > 0:
                logger.info("Using fallback input device: %s", device.get("name", index))
                return index

        raise RuntimeError("No input audio device was found.")

    def start(self):
        """Start recording from microphone."""
        with self._lock:
            self._chunks = []
            self._recording = True
            self._start_time = time.monotonic()
            self._current_rms = 0.0

        device = self._resolve_input_device()
        device_info = dict(sd.query_devices(device))
        stream_sample_rate = self._resolve_stream_sample_rate(device, device_info)
        self._stream_sample_rate = float(stream_sample_rate)
        self._active_device_name = str(device_info.get("name", device)).strip() or str(device)

        try:
            self._stream = sd.InputStream(
                samplerate=self._stream_sample_rate,
                channels=1,
                dtype="float32",
                blocksize=512,
                device=device,
                latency="low",
                clip_off=True,
                dither_off=True,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as exc:
            with self._lock:
                self._recording = False
                self._chunks = []
                self._current_rms = 0.0
            raise RuntimeError(f"Failed to start microphone input: {exc}") from exc

        logger.info(
            "Recording started (device=%s, stream_sr=%s, target_sr=%s)",
            self._active_device_name,
            int(self._stream_sample_rate),
            self._sample_rate,
        )

    def stop(self) -> Optional[np.ndarray]:
        """Stop recording and return audio as numpy array.

        Returns None if recording was too short (accidental tap).
        """
        self._recording = False
        duration = time.monotonic() - self._start_time

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if duration < self.config.min_duration:
            logger.info(f"Recording too short ({duration:.2f}s), ignoring")
            return None

        with self._lock:
            if not self._chunks:
                return None
            audio = np.concatenate(self._chunks)
            self._chunks = []

        audio = self._trim_silence(audio)
        if int(round(self._stream_sample_rate)) != self._sample_rate:
            audio = self._resample_audio(audio, self._stream_sample_rate, self._sample_rate)

        logger.info(
            "Recording stopped: %.2fs of audio (device=%s, rms=%.4f, peak=%.4f)",
            len(audio) / self._sample_rate,
            self._active_device_name,
            float(np.sqrt(np.mean(np.square(audio), dtype=np.float64))) if len(audio) else 0.0,
            float(np.max(np.abs(audio))) if len(audio) else 0.0,
        )
        return audio

    def _trim_silence(self, audio: np.ndarray) -> np.ndarray:
        """Trim leading and trailing silence."""
        if len(audio) == 0:
            return audio

        threshold = self._silence_threshold(audio)
        # Find first sample above threshold
        above = np.abs(audio) > threshold
        if not np.any(above):
            return audio  # All silence, return anyway (whisper handles this)

        first = np.argmax(above)
        last = len(audio) - np.argmax(above[::-1])

        # Keep more context for quiet starts/stops and whispered speech.
        pad = int(0.12 * self._stream_sample_rate)
        first = max(0, first - pad)
        last = min(len(audio), last + pad)

        return audio[first:last]

    def _silence_threshold(self, audio: np.ndarray) -> float:
        """Choose a trim threshold that stays conservative on quiet headset speech."""
        base = float(self.config.silence_threshold)
        abs_audio = np.abs(audio)
        peak = float(np.max(abs_audio))
        if peak <= 1e-6:
            return base

        noise_floor = float(np.percentile(abs_audio, 35))
        threshold = max(noise_floor * 2.2, peak * 0.05, 0.002)
        threshold = min(base, threshold)
        logger.debug(
            "Adaptive trim threshold %.4f (base=%.4f, noise=%.4f, peak=%.4f)",
            threshold,
            base,
            noise_floor,
            peak,
        )
        return threshold

    def _resolve_stream_sample_rate(self, device: int | str | None, device_info: dict) -> float:
        """Use the requested rate when supported, otherwise fall back to the device-native rate."""
        requested = float(self._sample_rate)
        try:
            sd.check_input_settings(device=device, samplerate=requested, channels=1, dtype="float32")
            return requested
        except Exception:
            default_rate = float(device_info.get("default_samplerate", requested))
            if default_rate > 0:
                try:
                    sd.check_input_settings(
                        device=device,
                        samplerate=default_rate,
                        channels=1,
                        dtype="float32",
                    )
                    logger.info(
                        "Requested %s Hz unsupported for %s; using device default %s Hz",
                        int(requested),
                        device_info.get("name", device),
                        int(default_rate),
                    )
                    return default_rate
                except Exception:
                    pass
        return requested

    @staticmethod
    def _resample_audio(audio: np.ndarray, from_rate: float, to_rate: int) -> np.ndarray:
        """Resample audio to the model rate using linear interpolation."""
        if len(audio) == 0 or int(round(from_rate)) == to_rate:
            return np.asarray(audio, dtype=np.float32)

        duration = len(audio) / float(from_rate)
        target_length = max(1, int(round(duration * to_rate)))
        src_positions = np.linspace(0.0, len(audio) - 1, num=len(audio), dtype=np.float64)
        dst_positions = np.linspace(0.0, len(audio) - 1, num=target_length, dtype=np.float64)
        resampled = np.interp(dst_positions, src_positions, audio).astype(np.float32)
        return resampled

    @property
    def current_rms(self) -> float:
        """Current audio input RMS level for waveform visualization."""
        return self._current_rms

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration(self) -> float:
        """Current recording duration in seconds."""
        if self._recording:
            return time.monotonic() - self._start_time
        return 0.0
