"""Text cleanup for Koe.

Cleans up raw transcription output:
- Removes filler words (um, uh, like, you know, etc.)
- Fixes capitalization and punctuation
- Joins sentence fragments
- Preserves the speaker's actual word choices and tone

Two modes:
1. "rules" — fast regex/rule-based cleanup, no extra model needed
2. "llm"   — uses a small local LLM for smarter cleanup
"""

import logging
import re
from typing import Optional

from koe.config import CleanupConfig
from koe.context import FormattingProfile
from koe.dictionary import PersonalDictionary

logger = logging.getLogger(__name__)

# Filler patterns to remove (word boundaries to avoid partial matches)
FILLER_PATTERNS = [
    r"\bum+\b",
    r"\buh+\b",
    r"\bah+\b",
    r"\beh+\b",
    r"\bhmm+\b",
    r"\bhuh\b",
    r"\blike\b(?=\s*,)",        # "like," as filler (before comma)
    r"\byou know\b",
    r"\byou know what I mean\b",
    r"\bif that makes sense\b",
    r"\bif you know what I mean\b",
    r"\bI mean\b",
    r"\bbasically\b",
    r"\bactually\b(?=\s*,)",    # "actually," as filler
    r"\bliterally\b(?=\s*,)",   # "literally," as filler
    r"^\s*so+\b(?:\s*,)?",      # leading "so" filler
    r"\bright\b(?=\s*,)",       # "right," as filler
    r"\bokay so\b",
    r"\byeah so\b",
    r"\bkind of\b",
    r"\bsort of\b",
    r"\bor something\b",
    r"\bor whatever\b",
    r"\bor something like that\b",
    r"\banyway\b(?=\s*,)",      # "anyway," as filler
    r"\bso yeah\b",
    r"\byeah\b(?=\s*,)",        # "yeah," as filler
]

# Compile into a single pattern
FILLER_REGEX = re.compile(
    "|".join(f"(?:{p})" for p in FILLER_PATTERNS),
    re.IGNORECASE,
)


class TextCleaner:
    """Cleans up raw transcription text."""

    def __init__(self, config: CleanupConfig):
        self.config = config
        self._llm = None
        self._dictionary = PersonalDictionary()

    def clean(self, text: str) -> str:
        """Clean up transcribed text.

        Args:
            text: Raw transcription from Whisper

        Returns:
            Cleaned text preserving the speaker's voice
        """
        if not self.config.enabled or not text:
            return text

        if self.config.mode == "llm":
            return self._clean_with_llm(text)
        return self._clean_with_rules(text)

    def clean_with_context(self, text: str, exe: str | None, title: str | None) -> str:
        """Clean text applying context-aware formatting based on active app."""
        if not self.config.enabled or not text:
            return text
        if self.config.mode == "llm":
            return self._clean_with_llm(text)
        from koe.context import detect_profile
        profile = detect_profile(exe, title)
        import logging as _lg
        _lg.getLogger(__name__).debug("Context profile: %s (exe=%s)", profile.label, exe)
        return self._clean_with_rules(text, profile)

    def _clean_with_rules(self, text: str, profile: "FormattingProfile | None" = None) -> str:
        """Rule-based text cleanup. Fast, no model needed."""
        original = text

        text = self._apply_spoken_punctuation(text)

        # Step 0: Remove word-level repetitions ("the the" → "the")
        text = re.sub(r'\b(\w+)(\s+\1)+\b', r'\1', text, flags=re.IGNORECASE)

        # Step 1: Remove filler words
        if self.config.remove_fillers and (profile is None or profile.remove_fillers):
            text = FILLER_REGEX.sub("", text)

        # Step 2: Clean up whitespace and punctuation artifacts
        text = re.sub(r"\s+", " ", text)  # Collapse multiple spaces
        text = re.sub(r"\s+,", ",", text)  # Remove space before comma
        text = re.sub(r",\s*,", ",", text)  # Remove double commas
        text = re.sub(r"^\s*,\s*", "", text)  # Remove leading comma
        text = re.sub(r"\s+\.", ".", text)  # Remove space before period
        text = re.sub(r"\.\.+", ".", text)  # Collapse multiple periods
        text = text.strip()

        # Step 3: Fix capitalization
        do_capitalize = self.config.fix_punctuation and (profile is None or profile.capitalize)
        if do_capitalize:
            # Capitalize first letter
            if text and text[0].islower():
                text = text[0].upper() + text[1:]

            # Capitalize after sentence-ending punctuation
            text = re.sub(
                r"([.!?])\s+([a-z])",
                lambda m: m.group(1) + " " + m.group(2).upper(),
                text,
            )

        # Step 4: Ensure ending punctuation
        do_punctuate = self.config.fix_punctuation and (profile is None or profile.add_punctuation)
        if do_punctuate:
            if text and text[-1] not in ".!?":
                # Add period unless it looks like an exclamation or question
                if any(text.lower().startswith(w) for w in [
                    "what", "why", "how", "when", "where", "who", "which",
                    "is it", "are you", "do you", "can you", "will you",
                    "does", "did", "could", "would", "should",
                ]):
                    text += "?"
                else:
                    text += "."

        # Step 5: Clean up any remaining artifacts
        text = text.strip()
        text = self._format_structured_speech(text)

        text = self._dictionary.apply(text)

        return text

    @staticmethod
    def _apply_spoken_punctuation(text: str) -> str:
        """Convert obvious spoken punctuation words into symbols."""
        replacements = [
            (r"\bcomma\b", ","),
            (r"\bperiod\b", "."),
            (r"\bfull stop\b", "."),
            (r"\bquestion mark\b", "?"),
            (r"\bexclamation mark\b", "!"),
            (r"\bnew line\b", "\n"),
            (r"\bnext line\b", "\n"),
            (r"\bnew paragraph\b", "\n\n"),
            (r"\bopen quote\b", "\u201c"),
            (r"\bclose quote\b", "\u201d"),
            (r"\bdash\b", "\u2014"),
            (r"\bcolon\b", ":"),
            (r"\bsemicolon\b", ";"),
        ]

        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _format_structured_speech(text: str) -> str:
        """Format as a list ONLY when the user is clearly enumerating distinct items.

        Rules to avoid false positives:
        - Numbered: numbers must be 1-2-3 in strict sequence, each item ≥ 5 words,
          ≥ 3 items, and list content covers > 55 % of the text.
        - Ordinal (first/second/third…): needs ≥ 3 markers, each item ≥ 6 words.
        - "then/next/finally" alone are NOT enough — too common in normal speech.
        """
        if not text:
            return text

        normalized = re.sub(r"\s+", " ", text).strip()

        # ── Explicit sequential numbered list ─────────────────────────────
        # e.g. "1 install the package 2 configure the settings 3 restart"
        # Requires strict 1-2-3... sequence, ≥ 3 items, each item ≥ 5 words.
        num_hits = re.findall(
            r"(?<!\d)([1-9])[.):]?\s+([A-Za-z][^0-9]{15,}?)(?=\s*[1-9][.):]?\s+[A-Za-z]|$)",
            normalized,
        )
        if len(num_hits) >= 3:
            nums = [int(n) for n, _ in num_hits]
            items = [item.strip(" ,.;") for _, item in num_hits]
            if (nums == list(range(1, len(nums) + 1))
                    and all(len(i.split()) >= 5 for i in items)
                    and sum(len(i) for i in items) / max(len(normalized), 1) > 0.55):
                return "\n".join(f"{n}. {i}" for n, i in zip(nums, items))

        # ── Ordinal-word list (first / second / third …) ──────────────────
        # e.g. "first install it, second configure it, third restart the server"
        # Requires ≥ 3 ordinals (NOT "then/next"), each item ≥ 6 words.
        _ORDINALS = (
            r"first|second|third|fourth|fifth|"
            r"sixth|seventh|eighth|ninth|tenth"
        )
        ordinal_hits = re.findall(
            rf"\b(?:{_ORDINALS})\b(?:\s+of\s+all)?[,:]?\s*",
            normalized, re.IGNORECASE,
        )
        if len(ordinal_hits) >= 3:
            parts = re.split(
                rf"\b(?:{_ORDINALS})\b(?:\s+of\s+all)?[,:]?\s*",
                normalized, flags=re.IGNORECASE,
            )
            items = [p.strip(" ,.;") for p in parts if len(p.strip(" ,.;").split()) >= 6]
            if len(items) >= 3:
                formatted = []
                for idx, item in enumerate(items, 1):
                    formatted.append(f"{idx}. {item[:1].upper() + item[1:]}")
                return "\n".join(formatted)

        return normalized

    def _clean_with_llm(self, text: str) -> str:
        """LLM-based cleanup using a small local model.

        Falls back to rules if LLM is not available.
        """
        try:
            self._ensure_llm()
        except Exception as e:
            logger.warning(f"LLM cleanup unavailable ({e}), falling back to rules")
            return self._clean_with_rules(text)

        prompt = (
            "Clean up this speech transcription. Fix grammar, punctuation, and "
            "remove filler words. Keep the original tone and word choices. "
            "Do NOT rewrite or make it formal. Just make it readable.\n\n"
            f"Input: {text}\n"
            "Output:"
        )

        try:
            response = self._llm(
                prompt,
                max_tokens=len(text.split()) * 2 + 50,
                temperature=0.1,
                stop=["\n\n", "Input:"],
            )
            cleaned = response["choices"][0]["text"].strip()

            # Sanity check: if LLM output is way longer or shorter, use rules
            ratio = len(cleaned) / max(len(text), 1)
            if ratio > 2.0 or ratio < 0.3:
                logger.warning("LLM output length suspicious, falling back to rules")
                return self._clean_with_rules(text)

            return self._dictionary.apply(cleaned)
        except Exception as e:
            logger.warning(f"LLM cleanup failed ({e}), falling back to rules")
            return self._clean_with_rules(text)

    def _ensure_llm(self):
        """Load local LLM if not loaded."""
        if self._llm is not None:
            return

        try:
            from llama_cpp import Llama
        except ImportError:
            raise RuntimeError(
                "LLM cleanup requires llama-cpp-python. "
                "Install with: pip install 'koe[llm]'"
            )

        from koe.config import MODELS_DIR

        # Look for any GGUF model in the models directory
        gguf_files = list(MODELS_DIR.glob("*.gguf"))
        if not gguf_files:
            raise RuntimeError(
                f"No .gguf model found in {MODELS_DIR}. "
                "Download a small model (e.g., phi-3-mini) and place it there."
            )

        model_path = str(gguf_files[0])
        logger.info(f"Loading LLM from {model_path}")

        self._llm = Llama(
            model_path=model_path,
            n_ctx=512,
            n_gpu_layers=-1,  # Offload all layers to GPU
            verbose=False,
        )

    def unload_llm(self):
        """Unload LLM to free memory."""
        if self._llm is not None:
            del self._llm
            self._llm = None
            logger.info("LLM unloaded")
