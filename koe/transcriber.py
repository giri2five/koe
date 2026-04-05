"""Speech-to-text transcription using faster-whisper.

Manages model loading, GPU memory, and inference.
Uses int8_float16 compute type for efficiency on NVIDIA GPUs.
"""

import logging
import os
import time
from typing import Optional

import numpy as np

from koe.config import TranscriptionConfig, MODELS_DIR

logger = logging.getLogger(__name__)

# Phrases Whisper commonly hallucinates on silence or near-silence recordings.
# These are filtered out as false positives before returning to the caller.
_HALLUCINATION_PHRASES: frozenset[str] = frozenset({
    "thank you",
    "thank you.",
    "thank you!",
    "thank you very much",
    "thank you very much.",
    "thank you very much!",
    "thank you for watching",
    "thank you for watching.",
    "thanks for watching",
    "thanks for watching.",
    "thanks for watching!",
    "please subscribe",
    "please subscribe.",
    "bye",
    "bye.",
    "bye bye",
    "bye bye.",
    "you",
    "you.",
    ".",
    "...",
    "…",
})


class Transcriber:
    """Whisper-based speech-to-text transcriber.

    Loads the model lazily on first use. Keeps it in memory for fast subsequent
    transcriptions. The model can be explicitly unloaded to free GPU VRAM.
    """

    def __init__(self, config: TranscriptionConfig):
        self.config = config
        self._model = None
        self._loaded_device: str | None = None
        self._loaded_compute_type: str | None = None

    def _load_model(self, device: str, compute_type: str):
        """Create a Whisper model instance for a specific runtime configuration."""
        from faster_whisper import WhisperModel
        cpu_threads = max(2, min(8, (os.cpu_count() or 4)))

        logger.info(
            f"Loading Whisper model '{self.config.model}' "
            f"(device={device}, compute={compute_type}, cpu_threads={cpu_threads})"
        )

        t0 = time.monotonic()
        model = WhisperModel(
            self.config.model,
            device=device,
            compute_type=compute_type,
            download_root=str(MODELS_DIR),
            cpu_threads=cpu_threads,
        )
        dt = time.monotonic() - t0
        logger.info(f"Model loaded in {dt:.1f}s")
        self._loaded_device = device
        self._loaded_compute_type = compute_type
        return model

    def _ensure_model(self):
        """Load model if not already loaded."""
        if self._model is not None:
            return

        try:
            self._model = self._load_model(self.config.device, self.config.compute_type)
        except Exception as exc:
            requested = (self.config.device, self.config.compute_type)
            if requested == ("cpu", "int8"):
                raise

            logger.warning(
                "Failed to load Whisper with device=%s compute=%s; falling back to CPU int8: %s",
                self.config.device,
                self.config.compute_type,
                exc,
            )
            self._model = self._load_model("cpu", "int8")

    def transcribe(self, audio: np.ndarray) -> Optional[str]:
        """Transcribe audio numpy array to text.

        Args:
            audio: float32 mono audio at 16kHz

        Returns:
            Transcribed text, or None if nothing was detected.
        """
        self._ensure_model()
        prepared = self._prepare_audio(audio)
        prefer_vad = self._should_use_vad(prepared)
        try:
            result = self._transcribe_with_loaded_model(prepared, vad_filter=prefer_vad)
            if result:
                return result
            if prefer_vad:
                return self._retry_quiet_audio(prepared)
            return None
        except RuntimeError as exc:
            if self._loaded_device == "cpu":
                raise

            message = str(exc).lower()
            if "cublas" not in message and "cuda" not in message:
                raise

            logger.warning(
                "CUDA transcription failed; retrying on CPU int8: %s",
                exc,
            )
            self.unload()
            self._model = self._load_model("cpu", "int8")
            result = self._transcribe_with_loaded_model(prepared, vad_filter=prefer_vad)
            if result:
                return result
            if prefer_vad:
                return self._retry_quiet_audio(prepared)
            return None

    def _transcribe_with_loaded_model(
        self,
        audio: np.ndarray,
        *,
        vad_filter: bool = True,
        beam_size_override: int | None = None,
    ) -> Optional[str]:
        """Run transcription using the currently loaded model."""
        t0 = time.monotonic()

        language = None if self.config.language == "auto" else self.config.language
        beam_size = beam_size_override or self._beam_size_for_audio(audio)

        segments, info = self._model.transcribe(
            audio,
            beam_size=beam_size,
            language=language,
            vad_filter=vad_filter,
            initial_prompt=(
                "Transcribe the speaker faithfully in natural written form. "
                "Keep casual tone casual. Preserve names carefully. "
                "Use punctuation naturally. "
                "If the speaker clearly enumerates items or steps with numbers, "
                "format them as a numbered list."
            ),
            vad_parameters=dict(
                min_silence_duration_ms=360,
                speech_pad_ms=420,
            ),
            suppress_blank=True,
            condition_on_previous_text=False,
            temperature=0.0,
            without_timestamps=True,
        )

        texts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                texts.append(text)

        dt = time.monotonic() - t0
        result = " ".join(texts) if texts else None

        if result:
            logger.info(
                "Transcribed in %.2fs (beam=%s, vad=%s): '%s...'",
                dt,
                beam_size,
                vad_filter,
                result[:80],
            )
        else:
            logger.info("No speech detected (took %.2fs, beam=%s, vad=%s)", dt, beam_size, vad_filter)

        if result and vad_filter and self._should_retry_without_vad(audio, result):
            logger.info("Retrying without VAD because decoded text looks too short for the clip")
            retry = self._transcribe_with_loaded_model(
                audio,
                vad_filter=False,
                beam_size_override=max(6, beam_size + 1),
            )
            if retry and len(retry.strip()) > len(result.strip()):
                return self._filter_hallucination(retry)

        return self._filter_hallucination(result)

    @staticmethod
    def _filter_hallucination(text: Optional[str]) -> Optional[str]:
        """Return None if the text is a known Whisper hallucination phrase."""
        if not text:
            return None
        normalized = text.strip().lower().rstrip(" .,!?")
        if normalized in _HALLUCINATION_PHRASES or text.strip().lower() in _HALLUCINATION_PHRASES:
            logger.warning("Filtered Whisper hallucination: %r", text)
            return None
        return text

    def _prepare_audio(self, audio: np.ndarray) -> np.ndarray:
        """Lightly normalize very quiet recordings without crushing dynamics."""
        if len(audio) == 0:
            return audio

        audio = np.asarray(audio, dtype=np.float32)
        audio = audio - float(np.mean(audio))
        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))

        if peak <= 1e-5:
            return audio

        gain = 1.0
        if peak < 0.12:
            gain = min(7.0, 0.42 / peak)
        elif peak < 0.18:
            gain = min(5.5, 0.34 / peak)
        if rms < 0.03:
            gain = max(gain, min(5.5, 0.07 / max(rms, 1e-5)))

        if gain <= 1.05:
            return audio

        boosted = np.clip(audio * gain, -0.98, 0.98).astype(np.float32)
        logger.info("Boosted quiet audio by %.2fx before transcription (rms=%.4f, peak=%.4f)", gain, rms, peak)
        return boosted

    def _retry_quiet_audio(self, audio: np.ndarray) -> Optional[str]:
        """Retry once with whisper VAD disabled to help with whispered or sparse speech."""
        retry_beam = max(6, int(self.config.beam_size) + 2)
        logger.info("Retrying transcription without VAD (beam=%s)", retry_beam)
        return self._transcribe_with_loaded_model(audio, vad_filter=False, beam_size_override=retry_beam)

    def _should_use_vad(self, audio: np.ndarray) -> bool:
        """Use VAD by default, but avoid it for very quiet clips where it drops all speech."""
        if len(audio) == 0:
            return True

        duration = len(audio) / 16000.0
        rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
        peak = float(np.max(np.abs(audio)))
        use_vad = not (
            (duration <= 10.0 and rms < 0.024 and peak < 0.28)
            or (duration <= 6.0 and rms < 0.032 and peak < 0.36)
        )
        logger.info(
            "Transcription audio profile: duration=%.2fs rms=%.4f peak=%.4f vad=%s",
            duration,
            rms,
            peak,
            use_vad,
        )
        return use_vad

    @staticmethod
    def _should_retry_without_vad(audio: np.ndarray, text: str) -> bool:
        """Detect when VAD likely clipped speech out of a longer utterance."""
        duration = len(audio) / 16000.0
        words = [word for word in text.strip().split() if word]
        if duration < 2.8:
            return False
        if len(words) <= 2:
            return True
        if duration >= 4.0 and len(words) <= 5:
            return True
        return False

    def _beam_size_for_audio(self, audio: np.ndarray) -> int:
        """Reduce CPU decode work on long clips while keeping short-utterance accuracy."""
        configured = max(1, int(self.config.beam_size))
        if self._loaded_device != "cpu":
            return configured

        duration = len(audio) / 16000.0
        if duration >= 20.0:
            return min(configured, 2)
        if duration >= 8.0:
            return min(configured, 3)
        return configured

    def transcribe_file_stream(
        self,
        path: str,
        on_segment,   # Callable[[str, float], None] — (partial_text, 0-1 progress)
    ) -> str:
        """Transcribe an audio file, calling on_segment as each segment is ready.

        Uses beam_size=1 for maximum speed on file mode. Streams partial results
        so the UI can update in real-time rather than waiting for the full file.

        Returns the final full transcript.
        """
        self._ensure_model()
        language = self.config.language if self.config.language != "auto" else None

        segments_iter, info = self._model.transcribe(
            path,
            language=language,
            beam_size=1,            # fastest for file mode; minimal accuracy trade-off
            vad_filter=True,
            word_timestamps=False,
            condition_on_previous_text=True,
            initial_prompt=(
                "Transcribe the audio accurately. "
                "Use natural punctuation. Preserve names and proper nouns carefully."
            ),
        )

        texts: list[str] = []
        total_duration = max(info.duration, 1.0)

        for seg in segments_iter:
            piece = seg.text.strip()
            if piece:
                texts.append(piece)
            partial  = " ".join(texts)
            progress = min(seg.end / total_duration, 0.99)
            try:
                on_segment(partial, progress)
            except Exception:
                pass

        final = " ".join(texts).strip()
        logger.info(
            "File transcription complete: source=%.1fs, chars=%d",
            info.duration, len(final),
        )
        return final

    def unload(self):
        """Unload model to free GPU memory."""
        if self._model is not None:
            del self._model
            self._model = None
            # Trigger CUDA memory cleanup
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            logger.info("Model unloaded")

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
