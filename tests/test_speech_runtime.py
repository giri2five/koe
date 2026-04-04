import numpy as np

from koe.audio import AudioRecorder
from koe.cleaner import TextCleaner
from koe.config import AudioConfig, TranscriptionConfig
from koe.transcriber import Transcriber
from koe.config import CleanupConfig


def test_audio_resample_changes_length():
    audio = np.linspace(-0.5, 0.5, num=4410, dtype=np.float32)
    resampled = AudioRecorder._resample_audio(audio, 44100.0, 16000)
    assert resampled.dtype == np.float32
    assert len(resampled) == 1600


def test_adaptive_silence_threshold_stays_below_base_for_quiet_clip():
    recorder = AudioRecorder(AudioConfig(silence_threshold=0.01))
    quiet = np.concatenate(
        [
            np.full(500, 0.0008, dtype=np.float32),
            np.full(500, 0.025, dtype=np.float32),
        ]
    )
    threshold = recorder._silence_threshold(quiet)
    assert 0.002 <= threshold < 0.01


def test_prepare_audio_removes_dc_offset_and_boosts_quiet_signal():
    transcriber = Transcriber(TranscriptionConfig(device="cpu", compute_type="int8"))
    audio = np.full(16000, 0.01, dtype=np.float32)
    audio[4000:8000] += 0.02

    prepared = transcriber._prepare_audio(audio)

    assert prepared.dtype == np.float32
    assert abs(float(np.mean(prepared))) < 1e-3
    assert float(np.max(np.abs(prepared))) > float(np.max(np.abs(audio)))


def test_should_disable_vad_for_quiet_short_clip():
    transcriber = Transcriber(TranscriptionConfig(device="cpu", compute_type="int8"))
    audio = np.full(16000 * 2, 0.01, dtype=np.float32)
    assert transcriber._should_use_vad(audio) is False


def test_should_keep_vad_for_louder_clip():
    transcriber = Transcriber(TranscriptionConfig(device="cpu", compute_type="int8"))
    audio = np.full(16000 * 2, 0.08, dtype=np.float32)
    assert transcriber._should_use_vad(audio) is True


def test_cpu_beam_size_scales_down_for_long_audio():
    transcriber = Transcriber(TranscriptionConfig(device="cpu", compute_type="int8", beam_size=5))
    transcriber._loaded_device = "cpu"
    short_audio = np.zeros(16000 * 3, dtype=np.float32)
    medium_audio = np.zeros(16000 * 10, dtype=np.float32)
    long_audio = np.zeros(16000 * 25, dtype=np.float32)

    assert transcriber._beam_size_for_audio(short_audio) == 5
    assert transcriber._beam_size_for_audio(medium_audio) == 3
    assert transcriber._beam_size_for_audio(long_audio) == 2


def test_cleaner_formats_spoken_numbered_list():
    cleaner = TextCleaner(CleanupConfig())
    text = "Going to the store for 1 apples 2 bananas 3 oranges"
    cleaned = cleaner.clean(text)
    assert cleaned == "1. apples\n2. bananas\n3. oranges"


def test_cleaner_formats_step_markers():
    cleaner = TextCleaner(CleanupConfig())
    text = "First open Notepad then type the title finally paste the notes"
    cleaned = cleaner.clean(text)
    assert cleaned == "1. Open Notepad\n2. Type the title\n3. Paste the notes"
