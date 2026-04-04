"""Tests for the hotkey module."""

from unittest.mock import Mock, patch

from koe.config import HotkeyConfig
from koe.hotkey import HotkeyListener


def test_delayed_record_stop_waits_before_callback():
    on_start = Mock()
    on_stop = Mock()
    on_mode_toggle = Mock()
    listener = HotkeyListener(
        config=HotkeyConfig(),
        on_record_start=on_start,
        on_record_stop=on_stop,
        on_mode_toggle=on_mode_toggle,
    )

    with patch("koe.hotkey.time.sleep") as mock_sleep:
        listener._delayed_record_stop()

    mock_sleep.assert_called_once_with(listener._release_delay_seconds)
    on_stop.assert_called_once()


def test_listener_uses_configured_trigger_key():
    listener = HotkeyListener(
        config=HotkeyConfig(trigger="alt+k", clipboard_toggle="alt+m"),
        on_record_start=Mock(),
        on_record_stop=Mock(),
        on_mode_toggle=Mock(),
    )

    with patch("koe.hotkey.keyboard.on_press_key") as on_press, patch(
        "koe.hotkey.keyboard.on_release_key"
    ) as on_release, patch("koe.hotkey.keyboard.add_hotkey"):
        listener.start()

    on_press.assert_called_once_with("k", listener._on_trigger_press, suppress=False)
    on_release.assert_called_once_with("k", listener._on_trigger_release, suppress=False)


def test_generic_alt_accepts_right_alt_variant():
    listener = HotkeyListener(
        config=HotkeyConfig(trigger="alt+k", clipboard_toggle="alt+m"),
        on_record_start=Mock(),
        on_record_stop=Mock(),
        on_mode_toggle=Mock(),
    )

    with patch("koe.hotkey.keyboard.is_pressed", side_effect=lambda key: key == "right alt"):
        assert listener._is_modifier_pressed("alt") is True


def test_trigger_press_uses_modifier_aliases():
    on_start = Mock()
    listener = HotkeyListener(
        config=HotkeyConfig(trigger="alt+k", clipboard_toggle="alt+m"),
        on_record_start=on_start,
        on_record_stop=Mock(),
        on_mode_toggle=Mock(),
    )

    with patch("koe.hotkey.keyboard.is_pressed", side_effect=lambda key: key == "right alt"), patch(
        "koe.hotkey.threading.Thread"
    ) as thread_cls:
        thread_instance = Mock()
        thread_cls.return_value = thread_instance
        listener._on_trigger_press(Mock())

    thread_cls.assert_called_once()
    thread_instance.start.assert_called_once()
