"""Context detection for Koe — detects active app and returns a formatting profile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class FormattingProfile:
    """Overrides applied on top of the user's CleanupConfig for a given context."""
    add_punctuation: bool = True    # add ending period / question mark
    capitalize: bool = True         # capitalize first letter & after sentences
    remove_fillers: bool = True     # strip um/uh/like etc.
    label: str = "Default"          # human-readable name for logging


# App name patterns → profile
_PROFILES: list[tuple[re.Pattern, FormattingProfile]] = [
    # Terminals / shells — no added punctuation, preserve case
    (re.compile(r"cmd\.exe|powershell|windowsterminal|wt\.exe|bash|mintty|alacritty|hyper", re.I),
     FormattingProfile(add_punctuation=False, capitalize=False, remove_fillers=True, label="Terminal")),

    # Code editors — no ending period, preserve case
    (re.compile(r"code\.exe|cursor\.exe|sublime|notepad\+\+|vim|nvim|emacs|rider|clion|pycharm|intellij|webstorm|atom|brackets", re.I),
     FormattingProfile(add_punctuation=False, capitalize=False, remove_fillers=True, label="Code editor")),

    # Messaging / chat — casual, no trailing period
    (re.compile(r"slack|teams|discord|telegram|whatsapp|signal|messenger|zoom|skype|mattermost|element", re.I),
     FormattingProfile(add_punctuation=False, capitalize=True, remove_fillers=True, label="Messaging")),

    # Browsers — full punctuation (could be forms, docs, anything)
    (re.compile(r"chrome\.exe|msedge\.exe|firefox\.exe|brave\.exe|opera\.exe|vivaldi", re.I),
     FormattingProfile(add_punctuation=True, capitalize=True, remove_fillers=True, label="Browser")),

    # Email clients — full formal punctuation
    (re.compile(r"outlook\.exe|thunderbird|mailbird|postbox|spark", re.I),
     FormattingProfile(add_punctuation=True, capitalize=True, remove_fillers=True, label="Email")),
]

_DEFAULT_PROFILE = FormattingProfile(label="Default")


def detect_profile(exe: Optional[str], title: Optional[str]) -> FormattingProfile:
    """Return a FormattingProfile for the given foreground window."""
    target = (exe or "") + " " + (title or "")
    for pattern, profile in _PROFILES:
        if pattern.search(target):
            return profile
    return _DEFAULT_PROFILE
