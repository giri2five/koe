"""Tests for the config module."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from koe.config import (
    KoeConfig,
    HotkeyConfig,
    AudioConfig,
    TranscriptionConfig,
    CleanupConfig,
    OutputConfig,
    UIConfig,
    load_config,
    save_config,
    _dataclass_to_dict,
    _update_dataclass,
)


class TestDefaults:
    def test_default_hotkey(self):
        config = KoeConfig()
        assert config.hotkey.trigger == "alt+k"
        assert config.hotkey.clipboard_toggle == ""

    def test_default_audio(self):
        config = KoeConfig()
        assert config.audio.sample_rate == 16000
        assert config.audio.device == "system_default"
        assert config.audio.output_device == "system_default"
        assert config.audio.min_duration == 0.3
        assert config.audio.max_duration == 120.0

    def test_default_transcription(self):
        config = KoeConfig()
        assert config.transcription.model == "base.en"
        assert config.transcription.device == "cuda"
        assert config.transcription.compute_type == "int8_float16"

    def test_default_cleanup(self):
        config = KoeConfig()
        assert config.cleanup.enabled is True
        assert config.cleanup.mode == "rules"
        assert config.cleanup.remove_fillers is True

    def test_default_output(self):
        config = KoeConfig()
        assert config.output.default_mode == "both"
        assert config.output.typing_speed == 0


class TestSerialization:
    def test_round_trip(self):
        config = KoeConfig()
        data = _dataclass_to_dict(config)
        assert data["hotkey"]["trigger"] == "alt+k"
        assert data["transcription"]["model"] == "base.en"
        assert isinstance(data["audio"]["sample_rate"], int)

    def test_update_dataclass(self):
        config = KoeConfig()
        _update_dataclass(config, {
            "transcription": {"model": "large-v3"},
            "output": {"default_mode": "clipboard"},
        })
        assert config.transcription.model == "large-v3"
        assert config.output.default_mode == "clipboard"
        # Unchanged values should remain
        assert config.hotkey.trigger == "alt+k"

    def test_ignores_unknown_keys(self):
        config = KoeConfig()
        _update_dataclass(config, {"nonexistent_key": "value"})
        # Should not raise


class TestFileIO:
    def test_save_and_load(self, tmp_path):
        config_path = tmp_path / "config.toml"
        koe_dir = tmp_path / ".koe"

        with patch("koe.config.CONFIG_PATH", config_path), \
             patch("koe.config.KOE_DIR", koe_dir), \
             patch("koe.config.MODELS_DIR", koe_dir / "models"):

            # Save
            config = KoeConfig()
            config.transcription.model = "small"
            save_config(config)
            assert config_path.exists()

            # Load
            loaded = load_config()
            assert loaded.transcription.model == "small"
            assert loaded.hotkey.trigger == "alt+k"

    def test_creates_default_on_first_run(self, tmp_path):
        config_path = tmp_path / "config.toml"
        koe_dir = tmp_path / ".koe"

        with patch("koe.config.CONFIG_PATH", config_path), \
             patch("koe.config.KOE_DIR", koe_dir), \
             patch("koe.config.MODELS_DIR", koe_dir / "models"):

            assert not config_path.exists()
            config = load_config()
            assert config_path.exists()
            assert config.transcription.model == "base"
