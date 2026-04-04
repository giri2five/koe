"""Audio device discovery helpers for Koe."""

from __future__ import annotations

from dataclasses import dataclass

import sounddevice as sd

SYSTEM_DEFAULT = "system_default"
LEGACY_DEFAULT = "default"


@dataclass(frozen=True)
class DeviceOption:
    """Selectable audio device option for input or output."""

    value: str
    label: str


def _query_devices() -> list[dict]:
    """Return all PortAudio devices as plain dictionaries."""
    return [dict(device) for device in sd.query_devices()]


def _default_index(kind: str) -> int | None:
    """Return the current system default device index for a direction."""
    default_input, default_output = sd.default.device
    index = default_input if kind == "input" else default_output
    if index is None:
        return None
    index = int(index)
    return index if index >= 0 else None


def get_default_device_name(kind: str) -> str | None:
    """Return the current system default device name for the given direction."""
    index = _default_index(kind)
    if index is None:
        return None

    try:
        device = sd.query_devices(index)
    except Exception:
        return None

    return str(device.get("name", "")).strip() or None


def _matches_kind(device: dict, kind: str) -> bool:
    """Check whether a PortAudio device supports the requested direction."""
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    return int(device.get(key, 0)) > 0


def _deduped_device_names(kind: str) -> list[str]:
    """Return unique device names that support the requested direction."""
    names: list[str] = []
    seen: set[str] = set()
    for device in _query_devices():
        if not _matches_kind(device, kind):
            continue
        name = str(device.get("name", "")).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def list_device_options(kind: str) -> list[DeviceOption]:
    """Return selectable options for audio device configuration."""
    current_default = get_default_device_name(kind) or "Unavailable"
    options = [
        DeviceOption(
            value=SYSTEM_DEFAULT,
            label=f"System default ({current_default})",
        )
    ]
    options.extend(DeviceOption(value=name, label=name) for name in _deduped_device_names(kind))
    return options


def resolve_device(selection: str | int | None, kind: str) -> int | None:
    """Resolve a configured device selection to a PortAudio device index."""
    if selection is None:
        return _default_index(kind)

    if isinstance(selection, int):
        return selection

    choice = selection.strip()
    if not choice or choice in {SYSTEM_DEFAULT, LEGACY_DEFAULT}:
        return _default_index(kind)

    if choice.isdigit():
        return int(choice)

    wanted = choice.casefold()
    for index, device in enumerate(_query_devices()):
        if not _matches_kind(device, kind):
            continue
        name = str(device.get("name", "")).strip()
        if wanted == name.casefold():
            return index

    for index, device in enumerate(_query_devices()):
        if not _matches_kind(device, kind):
            continue
        name = str(device.get("name", "")).strip()
        if wanted in name.casefold():
            return index

    return None


def describe_selection(selection: str | None, kind: str) -> str:
    """Human-readable description of a configured selection."""
    if not selection or selection in {SYSTEM_DEFAULT, LEGACY_DEFAULT}:
        return get_default_device_name(kind) or "System default"
    return selection
