"""Voice snippets for Koe — trigger phrases that expand to full templates."""

from __future__ import annotations

import logging
import re
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


def _save_raw(snippets: dict[str, str]):
    """Persist the snippets dict to disk."""
    import tomli_w
    KOE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SNIPPETS_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Koe voice snippets\n")
        f.write("# Say the trigger phrase to expand it instantly.\n\n")
        f.write(tomli_w.dumps({"snippets": snippets}))


class SnippetStore:
    """In-memory snippet lookup with disk persistence."""

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

    def all(self) -> list[dict]:
        """Return all snippets as a list of {trigger, expansion} dicts."""
        self._ensure_loaded()
        return [{"trigger": k, "expansion": v} for k, v in self._snippets.items()]

    def add(self, trigger: str, expansion: str) -> bool:
        """Add or update a snippet. Returns True on success."""
        self._ensure_loaded()
        trigger = trigger.strip().lower().rstrip(".")
        if not trigger or not expansion.strip():
            return False
        self._snippets[trigger] = expansion.strip()
        try:
            _save_raw(self._snippets)
            logger.info("Saved snippet: %r → %r", trigger, expansion[:60])
            return True
        except Exception as exc:
            logger.warning("Failed to save snippets: %s", exc)
            return False

    def delete(self, trigger: str) -> bool:
        """Remove a snippet. Returns True if it existed."""
        self._ensure_loaded()
        trigger = trigger.strip().lower()
        if trigger not in self._snippets:
            return False
        del self._snippets[trigger]
        try:
            _save_raw(self._snippets)
            return True
        except Exception as exc:
            logger.warning("Failed to save snippets after delete: %s", exc)
            return False

    def suggest(self, history: list[dict]) -> list[dict]:
        """Analyse dictation history and suggest potential snippets."""
        self._ensure_loaded()
        texts = [e.get("text", "") for e in history if e.get("text")]
        if not texts:
            return []

        suggestions: list[dict] = []
        seen_triggers = set(self._snippets.keys())

        # ── Email addresses ────────────────────────────────────────────────
        for text in texts:
            m = re.search(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b', text)
            if m:
                email = m.group(0)
                trigger = "my email"
                if trigger not in seen_triggers and not any(
                    s["trigger"] == trigger for s in suggestions
                ):
                    suggestions.append({
                        "trigger": trigger,
                        "expansion": email,
                        "reason": "email address",
                    })

        # ── Repeated phrases (4-7 word phrases appearing 2+ times) ────────
        from collections import Counter
        phrase_counts: Counter = Counter()
        for text in texts:
            words = text.split()
            for length in (4, 5, 6, 7):
                for i in range(len(words) - length + 1):
                    phrase = " ".join(words[i : i + length]).strip(".,!?")
                    if len(phrase) > 15:
                        phrase_counts[phrase.lower()] += 1

        for phrase, count in phrase_counts.most_common(5):
            if count < 2:
                break
            if phrase in seen_triggers:
                continue
            words = phrase.split()
            trigger = " ".join(words[:2]).lower().strip(".,!?")
            if trigger in seen_triggers or any(s["trigger"] == trigger for s in suggestions):
                continue
            suggestions.append({
                "trigger": trigger,
                "expansion": phrase,
                "reason": f"said {count}\u00d7 in history",
            })

        return suggestions[:5]

    @property
    def path(self) -> Path:
        return SNIPPETS_PATH
