#!/usr/bin/env python3
"""
Unit tests for utility functions in telegram_bot/utils.py.

These tests validate the markdown conversion, message formatting,
and text chunking functionality for Telegram messages.
"""

from telegram_bot.utils import (
    _is_section_header,
    _split_text_into_chunks,
    clean_ai_response,
    convert_markdown_to_telegram,
)


class TestConvertMarkdownToTelegram:
    """Tests for convert_markdown_to_telegram function."""

    def test_converts_headers_to_bold(self):
        """Test that ## headers are converted to *bold* with newlines."""
        text = "## This is a header\nSome content"
        result = convert_markdown_to_telegram(text)
        assert result == "*This is a header*\n\nSome content"

    def test_converts_multiple_headers(self):
        """Test that multiple headers are all converted."""
        text = "## First Header\nContent\n## Second Header\nMore content"
        result = convert_markdown_to_telegram(text)
        assert "*First Header*" in result
        assert "*Second Header*" in result

    def test_converts_double_asterisks_to_single(self):
        """Test that **bold** is converted to *bold*."""
        text = "This is **bold text** in a sentence"
        result = convert_markdown_to_telegram(text)
        assert result == "This is *bold text* in a sentence"

    def test_converts_multiple_bold_sections(self):
        """Test that multiple **bold** sections are all converted."""
        text = "**First bold** and **second bold**"
        result = convert_markdown_to_telegram(text)
        assert result == "*First bold* and *second bold*"

    def test_removes_quote_markers(self):
        """Test that > quote markers are removed."""
        text = "> This is a quote\n> Another line"
        result = convert_markdown_to_telegram(text)
        assert result == "This is a quote\nAnother line"

    def test_handles_combined_formatting(self):
        """Test that all conversions work together."""
        text = "## Header\n**Bold text**\n> Quote"
        result = convert_markdown_to_telegram(text)
        assert "*Header*" in result
        assert "*Bold text*" in result
        assert "> " not in result

    def test_handles_empty_string(self):
        """Test that empty strings are handled correctly."""
        assert convert_markdown_to_telegram("") == ""

    def test_handles_none(self):
        """Test that None is handled correctly."""
        assert convert_markdown_to_telegram(None) is None

    def test_preserves_telegram_markdown(self):
        """Test that existing Telegram markdown is preserved."""
        text = "*Already bold* and _italic_ with `code`"
        result = convert_markdown_to_telegram(text)
        assert "*Already bold*" in result
        assert "_italic_" in result
        assert "`code`" in result


class TestCleanAiResponse:
    """Tests for clean_ai_response function."""

    def test_cleans_basic_string_response(self):
        """Test that basic string responses are handled."""
        response = "This is a simple response"
        result = clean_ai_response(response)
        assert result == "This is a simple response"

    def test_removes_code_block_markers(self):
        """Test that code block markers are removed."""
        response = "```\nCode content\n```"
        result = clean_ai_response(response)
        assert result == "Code content"

    def test_removes_leading_dash(self):
        """Test that leading dash is removed from first line."""
        response = "- First item"
        result = clean_ai_response(response)
        assert result == "First item"

    def test_converts_markdown_to_telegram(self):
        """Test that markdown is converted to Telegram format."""
        response = "## Header\n**Bold text**"
        result = clean_ai_response(response)
        assert "*Header*" in result
        assert "*Bold text*" in result
        assert "##" not in result

    def test_handles_multiline_response(self):
        """Test that multiline responses are handled correctly."""
        response = "Line 1\nLine 2\nLine 3"
        result = clean_ai_response(response)
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_handles_non_string_response(self):
        """Test that non-string responses are converted to strings."""
        response = 42
        result = clean_ai_response(response)
        assert result == "42"


class TestIsSectionHeader:
    """Tests for _is_section_header function."""

    def test_identifies_simple_header(self):
        """Test that simple bold headers are identified."""
        assert _is_section_header("*Header*") is True

    def test_identifies_header_with_spaces(self):
        """Test that headers with leading/trailing spaces are identified."""
        assert _is_section_header("  *Header*  ") is True

    def test_identifies_long_header(self):
        """Test that longer headers are identified."""
        assert _is_section_header("*This is a longer section header*") is True

    def test_rejects_non_header_text(self):
        """Test that regular text is not identified as header."""
        assert _is_section_header("Regular text") is False

    def test_rejects_text_with_single_asterisk(self):
        """Test that text with only one asterisk is not a header."""
        assert _is_section_header("*Not closed") is False

    def test_rejects_empty_bold(self):
        """Test that ** is not a header (too short)."""
        assert _is_section_header("**") is False

    def test_rejects_asterisk_in_middle(self):
        """Test that text with asterisks not at start/end is not a header."""
        assert _is_section_header("Text *bold* more text") is False


class TestSplitTextIntoChunks:
    """Tests for _split_text_into_chunks function."""

    def test_short_text_not_split(self):
        """Test that text shorter than max_length is not split."""
        text = "Short text"
        result = _split_text_into_chunks(text, max_length=100)
        assert result == [text]

    def test_splits_at_newlines(self):
        """Test that text is split at newlines when necessary."""
        text = "Line 1\n" + "x" * 100 + "\nLine 3"
        result = _split_text_into_chunks(text, max_length=50)
        assert len(result) > 1

    def test_splits_before_section_header(self):
        """Test that text is split before section headers when approaching limit."""
        # 450 chars + newline + 13 char header + newline = 465 total
        # At 465/500 = 93%, we should split when we see the header is coming
        # But the logic checks if we're at 80% BEFORE adding the next line with the header
        # So: 450 chars, then we see next line is a header, and 450/500 = 90% > 80%
        # Actually, let me make this more explicit to trigger the split
        text = "a" * 420 + "\n*New Section*\n" + "b" * 100
        result = _split_text_into_chunks(text, max_length=500)
        # At 420 chars, next line is header, 420/500 = 84% > 80%, should split
        assert len(result) == 2
        assert "*New Section*" in result[1]

    def test_does_not_split_early_if_not_near_limit(self):
        """Test that text is not split early if we're not near the limit."""
        text = "a" * 100 + "\n*New Section*\n" + "b" * 100
        result = _split_text_into_chunks(text, max_length=1000)
        # Should not split since we're only at ~20% of limit
        assert len(result) == 1

    def test_splits_very_long_lines(self):
        """Test that very long lines are split at word boundaries."""
        text = " ".join(["word"] * 200)
        result = _split_text_into_chunks(text, max_length=100)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 100

    def test_preserves_content(self):
        """Test that all content is preserved after splitting."""
        text = "Line 1\nLine 2\n*Section*\nLine 3\nLine 4"
        result = _split_text_into_chunks(text, max_length=30)
        rejoined = " ".join(result)
        # All original words should be in the rejoined text
        for word in text.split():
            assert word in rejoined

    def test_handles_empty_string(self):
        """Test that empty strings are handled correctly."""
        result = _split_text_into_chunks("", max_length=100)
        assert result == [""]

    def test_splits_multiple_sections(self):
        """Test that multiple sections are split correctly."""
        sections = []
        for i in range(5):
            sections.append(f"*Section {i}*\n" + "x" * 300)
        text = "\n\n".join(sections)
        result = _split_text_into_chunks(text, max_length=500)
        assert len(result) >= 3  # Should split into multiple chunks


class TestEndToEndFormatting:
    """End-to-end tests for the full formatting pipeline."""

    def test_formats_analysis_response(self):
        """Test formatting of a typical analysis response."""
        response = """## Analysis Results

**Summary:** Your sleep was good this week

## Details
- Average: 7.5 hours
- Best night: Monday

> This is an important note"""

        result = clean_ai_response(response)

        # Should convert headers
        assert "*Analysis Results*" in result
        assert "*Details*" in result

        # Should convert bold
        assert "*Summary:*" in result

        # Should remove quote markers
        assert "> " not in result
        assert "This is an important note" in result

    def test_formats_short_confirmation(self):
        """Test formatting of a short confirmation message."""
        response = "✅ Zapisano do dziennej notatki z tagami: #Tag1 #Tag2"
        result = clean_ai_response(response)
        assert result == response  # Should be unchanged

    def test_formats_structured_data(self):
        """Test formatting of structured data response."""
        response = """*Twój sen w tym tygodniu:*

Średni wynik: 82/100
Średni czas: 7h 15min

Wygląda na to, że spałeś dobrze!"""

        result = clean_ai_response(response)
        # Should preserve the structure
        assert "*Twój sen w tym tygodniu:*" in result
        assert "82/100" in result
        assert "7h 15min" in result

    def test_handles_long_response_with_sections(self):
        """Test that long responses with sections can be chunked."""
        response = "*Section 1*\n" + "x" * 400 + "\n\n*Section 2*\n" + "y" * 400
        cleaned = clean_ai_response(response)
        chunks = _split_text_into_chunks(cleaned, max_length=500)

        # Should split into multiple chunks
        assert len(chunks) >= 2

        # Section headers should be at the start of chunks
        for i, chunk in enumerate(chunks):
            if "*Section" in chunk and i > 0:
                # If a section appears in a non-first chunk, it should be at/near the start
                lines = chunk.split("\n")
                # Find which line has the section header
                for j, line in enumerate(lines[:5]):  # Check first 5 lines
                    if "*Section" in line:
                        assert j <= 2  # Should be in first few lines
