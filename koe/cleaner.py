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
    r"\blike\b(?=\s*,)",  # "like," as filler (before comma)
    r"\byou know\b",
    r"\bI mean\b",
    r"\bbasically\b",
    r"\bactually\b(?=\s*,)",  # "actually," as filler
    r"\bliterally\b(?=\s*,)",  # "literally," as filler
    r"^\s*so+\b(?:\s*,)?",  # leading "so" filler
    r"\bright\b(?=\s*,)",  # "right," as filler
    r"\bokay so\b",
    r"\byeah so\b",
    r"\bkind of\b",
    r"\bsort of\b",
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

    def _clean_with_rules(self, text: str) -> str:
        """Rule-based text cleanup. Fast, no model needed."""
        original = text

        text = self._apply_spoken_punctuation(text)

        # Step 1: Remove filler words
        if self.config.remove_fillers:
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
        if self.config.fix_punctuation:
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
        if self.config.fix_punctuation:
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
        ]

        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _format_structured_speech(text: str) -> str:
        """Shape obvious numbered speech and step-like dictation into readable lines."""
        if not text:
            return text

        normalized = re.sub(r"\s+", " ", text).strip()

        numbered = re.findall(r"(\d+)[\).\:-]?\s+([^0-9]+?)(?=(?:\s+\d+[\).\:-]?\s)|$)", normalized)
        if len(numbered) >= 2:
            lines = [f"{index}. {item.strip(' ,.;')}" for index, item in numbered]
            return "\n".join(lines)

        step_markers = re.split(
            r"\b(?:first|second|third|fourth|fifth|then|next|after that|finally|lastly)\b[:,]?\s*",
            normalized,
            flags=re.IGNORECASE,
        )
        marker_hits = re.findall(
            r"\b(?:first|second|third|fourth|fifth|then|next|after that|finally|lastly)\b[:,]?\s*",
            normalized,
            flags=re.IGNORECASE,
        )
        if len(marker_hits) >= 2:
            items = [segment.strip(" ,.;") for segment in step_markers if segment.strip(" ,.;")]
            if len(items) >= 2:
                formatted = []
                for idx, item in enumerate(items, start=1):
                    if item and item[0].islower():
                        item = item[0].upper() + item[1:]
                    formatted.append(f"{idx}. {item}")
                return "\n".join(formatted)

        return text

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
