"""Personal dictionary for Koe.

Loads word replacement rules from ~/.koe/dictionary.txt.
Format: one rule per line, "wrong -> correct" (case-insensitive matching).
Lines starting with # are comments.

Example:
    # Technical terms
    kelp dao -> KelpDAO
    defi -> DeFi
    eth -> ETH
    gpt four -> GPT-4
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DICT_PATH = Path.home() / ".koe" / "dictionary.txt"

_DEFAULT_CONTENT = """\
# Koe Personal Dictionary
# One replacement per line: wrong spelling -> correct spelling
# Lines starting with # are comments. Matching is case-insensitive.
#
# Examples:
#   kelp dao -> KelpDAO
#   defi -> DeFi
#   eth -> ETH
#   your name -> Your Name
"""


class PersonalDictionary:
    """Applies user-defined word replacements after transcription."""

    def __init__(self):
        self._rules: list[tuple[re.Pattern, str]] = []
        self._mtime: float | None = None
        self._ensure_file()
        self._load()

    def _ensure_file(self):
        if not DICT_PATH.exists():
            DICT_PATH.parent.mkdir(parents=True, exist_ok=True)
            DICT_PATH.write_text(_DEFAULT_CONTENT, encoding="utf-8")

    def _load(self):
        try:
            mtime = DICT_PATH.stat().st_mtime
            if mtime == self._mtime:
                return
            self._mtime = mtime
            rules = []
            for line in DICT_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "->" not in line:
                    continue
                wrong, _, correct = line.partition("->")
                wrong   = wrong.strip()
                correct = correct.strip()
                if wrong and correct:
                    pattern = re.compile(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)", re.IGNORECASE)
                    rules.append((pattern, correct))
            self._rules = rules
            if rules:
                logger.info("Dictionary loaded: %d rules from %s", len(rules), DICT_PATH)
        except Exception as exc:
            logger.warning("Could not load dictionary: %s", exc)

    def apply(self, text: str) -> str:
        """Apply all dictionary rules to text. Reloads file if changed."""
        self._load()
        for pattern, replacement in self._rules:
            text = pattern.sub(replacement, text)
        return text
