"""Voice snippets for Koe — trigger phrases that expand to full templates."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

KOE_DIR = Path.home() / ".koe"
SNIPPETS_PATH = KOE_DIR / "snippets.toml"

_DEFAULT_SNIPPETS = """\
# Koe voice snippets
# Each entry maps a spoken trigger phrase to an expansion.
# The trigger must match the full transcription (case-insensitive).
#
# Examples:
# "my email" = "hello@example.com"
# "sign off" = "Best regards,\\nYour Name"
# "brb" = "Be right back."

[snippets]
"""


def _load_raw() -> dict[str, str]:
    """Load snippets from disk, creating defaults if file absent."""
    import sys
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    KOE_DIR.mkdir(parents=True, exist_ok=True)
    if not SNIPPETS_PATH.exists():
        SNIPPETS_PATH.write_text(_DEFAULT_SNIPPETS, encoding="utf-8")
        return {}

    try:
        data = tomllib.loads(SNIPPETS_PATH.read_text(encoding="utf-8"))
        return {k.strip().lower(): str(v) for k, v in data.get("snippets", {}).items()}
    except Exception as exc:
        logger.warning("Failed to load snippets: %s", exc)
        return {}


class SnippetStore:
    """In-memory snippet lookup that reloads from disk each session."""

    def __init__(self):
        self._snippets: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self._snippets = _load_raw()
            self._loaded = True
            logger.info("Loaded %d snippet(s) from %s", len(self._snippets), SNIPPETS_PATH)

    def reload(self):
        """Force reload from disk."""
        self._loaded = False
        self._ensure_loaded()

    def match(self, text: str) -> str | None:
        """Return expansion if text matches a trigger, else None."""
        self._ensure_loaded()
        return self._snippets.get(text.strip().lower())

    def count(self) -> int:
        self._ensure_loaded()
        return len(self._snippets)

    @property
    def path(self) -> Path:
        return SNIPPETS_PATH
