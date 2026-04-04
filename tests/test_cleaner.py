"""Tests for the text cleaner module."""

import pytest
from koe.config import CleanupConfig
from koe.cleaner import TextCleaner


@pytest.fixture
def cleaner():
    config = CleanupConfig(
        enabled=True,
        mode="rules",
        remove_fillers=True,
        fix_punctuation=True,
        fix_grammar=True,
        preserve_style=True,
    )
    return TextCleaner(config)


@pytest.fixture
def cleaner_disabled():
    config = CleanupConfig(enabled=False)
    return TextCleaner(config)


class TestFillerRemoval:
    def test_removes_um(self, cleaner):
        result = cleaner.clean("um I was thinking about it")
        assert "um" not in result.lower()
        assert "thinking" in result

    def test_removes_uh(self, cleaner):
        result = cleaner.clean("so uh we need to fix this")
        assert "uh" not in result.lower()

    def test_removes_you_know(self, cleaner):
        result = cleaner.clean("it's you know really important")
        assert "you know" not in result.lower()

    def test_removes_basically(self, cleaner):
        result = cleaner.clean("basically the server is down")
        assert "basically" not in result.lower()

    def test_removes_i_mean(self, cleaner):
        result = cleaner.clean("I mean the code works fine")
        assert "I mean" not in result

    def test_preserves_real_words(self, cleaner):
        """'like' as a verb should be preserved."""
        result = cleaner.clean("I like this approach")
        assert "like" in result.lower()

    def test_multiple_fillers(self, cleaner):
        result = cleaner.clean("um so uh you know basically it works")
        assert "it works" in result.lower()


class TestPunctuation:
    def test_capitalizes_first_letter(self, cleaner):
        result = cleaner.clean("the server is down")
        assert result[0] == "T"

    def test_adds_period(self, cleaner):
        result = cleaner.clean("the server is down")
        assert result.endswith(".")

    def test_adds_question_mark(self, cleaner):
        result = cleaner.clean("what time is the meeting")
        assert result.endswith("?")

    def test_preserves_existing_punctuation(self, cleaner):
        result = cleaner.clean("The server is down!")
        assert result.endswith("!")

    def test_capitalizes_after_period(self, cleaner):
        result = cleaner.clean("first thing. second thing")
        assert "Second" in result


class TestWhitespace:
    def test_collapses_spaces(self, cleaner):
        result = cleaner.clean("too   many    spaces")
        assert "   " not in result
        assert "  " not in result

    def test_strips_whitespace(self, cleaner):
        result = cleaner.clean("  hello world  ")
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_removes_double_commas(self, cleaner):
        result = cleaner.clean("first,, second")
        assert ",," not in result


class TestDisabled:
    def test_returns_unchanged(self, cleaner_disabled):
        text = "um uh you know whatever"
        result = cleaner_disabled.clean(text)
        assert result == text


class TestEmptyInput:
    def test_empty_string(self, cleaner):
        assert cleaner.clean("") == ""

    def test_none_like(self, cleaner):
        assert cleaner.clean("") == ""


class TestRealWorldExamples:
    """Test with examples that simulate actual speech patterns."""

    def test_casual_speech(self, cleaner):
        text = "um so basically I was thinking we should you know deploy on Friday"
        result = cleaner.clean(text)
        assert "deploy" in result
        assert "Friday" in result
        assert result[0].isupper()
        assert result[-1] in ".!?"

    def test_technical_speech(self, cleaner):
        text = "the API endpoint uh returns a 500 error when you send a POST request"
        result = cleaner.clean(text)
        assert "API" in result
        assert "500" in result
        assert "POST" in result
        assert "uh" not in result

    def test_short_utterance(self, cleaner):
        text = "yes"
        result = cleaner.clean(text)
        assert result == "Yes."

    def test_question(self, cleaner):
        text = "when is the deadline"
        result = cleaner.clean(text)
        assert result.endswith("?")
