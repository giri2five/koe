"""Tests for the output module."""

from unittest.mock import Mock, patch

import pytest

from koe.config import OutputConfig
from koe.output import DeliveryResult, OutputEngine, OutputMode, WindowTarget


@pytest.fixture
def engine():
    config = OutputConfig(default_mode="type", typing_speed=0)
    return OutputEngine(config)


@pytest.fixture
def clipboard_engine():
    config = OutputConfig(default_mode="clipboard", typing_speed=0)
    return OutputEngine(config)


@pytest.fixture
def both_engine():
    config = OutputConfig(default_mode="both", typing_speed=0)
    return OutputEngine(config)


class TestModeToggle:
    def test_starts_in_configured_mode(self, engine):
        assert engine.mode == OutputMode.TYPE

    def test_toggles_to_both(self, engine):
        mode = engine.toggle_mode()
        assert mode == OutputMode.BOTH
        assert engine.mode == OutputMode.BOTH

    def test_toggles_back_to_type(self, engine):
        engine.toggle_mode()
        mode = engine.toggle_mode()
        assert mode == OutputMode.TYPE

    def test_starts_in_clipboard_mode(self, clipboard_engine):
        assert clipboard_engine.mode == OutputMode.CLIPBOARD

    def test_starts_in_both_mode(self, both_engine):
        assert both_engine.mode == OutputMode.BOTH


class TestDeliver:
    def test_empty_text_does_nothing(self, engine):
        result = engine.deliver("")
        assert result == DeliveryResult(reason="empty")

    @patch("koe.output.pyperclip")
    def test_clipboard_copies_text(self, mock_pyperclip, clipboard_engine):
        clipboard_engine._wait_for_modifiers_release = Mock()
        clipboard_engine.get_foreground_window = Mock(return_value=WindowTarget(hwnd=123, pid=1))
        clipboard_engine._paste_clipboard = Mock(return_value=True)

        result = clipboard_engine.deliver("hello world", target_hwnd=WindowTarget(hwnd=123, pid=1))

        mock_pyperclip.copy.assert_called_once_with("hello world")
        assert result == DeliveryResult(copied=True, pasted=True, delivered=True, reason="pasted")

    @patch("koe.output.pyperclip")
    def test_clipboard_still_pastes_when_focus_changes(self, mock_pyperclip, clipboard_engine):
        clipboard_engine._wait_for_modifiers_release = Mock()
        clipboard_engine.get_foreground_window = Mock(return_value=WindowTarget(hwnd=456, pid=2))
        clipboard_engine._paste_clipboard = Mock(return_value=True)

        result = clipboard_engine.deliver("hello world", target_hwnd=WindowTarget(hwnd=123, pid=1))

        mock_pyperclip.copy.assert_called_once_with("hello world")
        clipboard_engine._paste_clipboard.assert_called_once()
        assert result == DeliveryResult(copied=True, pasted=True, delivered=True, reason="pasted")

    @patch("koe.output.pyperclip")
    def test_type_mode_falls_back_to_clipboard_when_typing_fails(self, mock_pyperclip, engine):
        engine._type_text = Mock(return_value=False)
        engine._wait_for_modifiers_release = Mock()
        engine.get_foreground_window = Mock(return_value=WindowTarget(hwnd=123, pid=1))
        engine._paste_clipboard = Mock(return_value=True)

        result = engine.deliver("hello world", target_hwnd=WindowTarget(hwnd=123, pid=1))

        mock_pyperclip.copy.assert_called_once_with("hello world")
        engine._paste_clipboard.assert_called_once()
        assert result.delivered is True
        assert result.copied is True
        assert result.pasted is True
        assert result.reason == "clipboard_fallback"

    @patch("koe.output.keyboard")
    def test_keyboard_paste_fallback_uses_keyboard_library(self, mock_keyboard):
        with patch("koe.output.time.sleep"):
            assert OutputEngine._keyboard_paste_fallback() is True

        assert mock_keyboard.release.call_count == 4
        mock_keyboard.send.assert_called_once_with("ctrl+v")

    def test_keyboard_type_fallback_uses_keyboard_library(self, engine):
        with patch("koe.output.keyboard") as mock_keyboard, patch("koe.output.time.sleep"):
            assert engine._keyboard_type_fallback("hello") is True

        assert mock_keyboard.release.call_count == 4
        mock_keyboard.write.assert_called_once()

    @patch("koe.output.pyperclip")
    def test_clipboard_falls_back_to_typing_when_paste_fails(self, mock_pyperclip, clipboard_engine):
        clipboard_engine._wait_for_modifiers_release = Mock()
        clipboard_engine.get_foreground_window = Mock(return_value=WindowTarget(hwnd=123, pid=1))
        clipboard_engine._paste_clipboard = Mock(return_value=False)
        clipboard_engine._type_text = Mock(return_value=True)

        result = clipboard_engine.deliver("hello world", target_hwnd=WindowTarget(hwnd=123, pid=1))

        mock_pyperclip.copy.assert_called_once_with("hello world")
        clipboard_engine._type_text.assert_called_once()
        assert result == DeliveryResult(
            copied=True,
            typed=True,
            delivered=True,
            reason="typed_fallback",
        )

    def test_same_target_allows_same_process_different_hwnd(self, clipboard_engine):
        assert clipboard_engine._same_target(
            WindowTarget(hwnd=1, pid=77),
            WindowTarget(hwnd=2, pid=77),
        )

    @patch("koe.output.pyperclip")
    def test_both_mode_copies_and_types(self, mock_pyperclip, both_engine):
        both_engine._wait_for_modifiers_release = Mock()
        both_engine.get_foreground_window = Mock(return_value=WindowTarget(hwnd=123, pid=1))
        both_engine._paste_clipboard = Mock(return_value=False)
        both_engine._type_text = Mock(return_value=True)

        result = both_engine.deliver("hello world", target_hwnd=WindowTarget(hwnd=123, pid=1))

        mock_pyperclip.copy.assert_called_once_with("hello world")
        both_engine._paste_clipboard.assert_called_once()
        both_engine._type_text.assert_called_once_with("hello world", WindowTarget(hwnd=123, pid=1))
        assert result == DeliveryResult(
            copied=True,
            typed=True,
            delivered=True,
            reason="copied_and_typed",
        )

    @patch("koe.output.pyperclip")
    def test_both_mode_falls_back_to_paste(self, mock_pyperclip, both_engine):
        both_engine._type_text = Mock(return_value=False)
        both_engine._wait_for_modifiers_release = Mock()
        both_engine.get_foreground_window = Mock(return_value=WindowTarget(hwnd=123, pid=1))
        both_engine._paste_clipboard = Mock(return_value=True)

        result = both_engine.deliver("hello world", target_hwnd=WindowTarget(hwnd=123, pid=1))

        mock_pyperclip.copy.assert_called_once_with("hello world")
        both_engine._paste_clipboard.assert_called_once()
        assert result == DeliveryResult(
            copied=True,
            pasted=True,
            delivered=True,
            reason="copied_and_pasted",
        )
