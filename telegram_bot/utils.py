"""Utility functions for the Telegram bot."""

import json
import re
from pathlib import Path
from typing import Optional, Union

from loguru import logger
from pydantic import BaseModel
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from telegram_bot.ai_assistant.agents.polish_product_search_agent import ProductSearchResult


def get_user_directory(base_dir: Union[str, Path], user_id: Union[int, str], subdir: Optional[str] = None) -> Path:
    """
    Get a user-specific directory path, creating it if it doesn't exist.

    Args:
        base_dir: Base directory path
        user_id: Telegram user ID
        subdir: Optional subdirectory within the user directory

    Returns:
        Path object for the user directory
    """
    # Ensure base_dir is a Path object
    if isinstance(base_dir, str):
        base_dir = Path(base_dir)

    # Convert user_id to string if it's an integer
    user_id_str = str(user_id)

    # Create the user directory path
    user_dir = base_dir / "user" / user_id_str

    # Add subdirectory if specified
    if subdir:
        user_dir = user_dir / subdir

    # Ensure the directory exists
    user_dir.mkdir(parents=True, exist_ok=True)

    return user_dir


def _format_product_search_result(data: ProductSearchResult) -> str:
    """Format ProductSearchResult for display."""
    lines = ["🔍 *Search Results*", ""]

    if data.offers:
        lines.append("📋 *Best Offers:*")
        for i, offer in enumerate(data.offers, 1):
            lines.append(f"{i}. *{offer.name}*")
            lines.append(f"   💰 Price: {offer.price} PLN")
            lines.append(f"   🏪 Shop: {offer.shop}")
            lines.append(f"   🏷️ Discount: {offer.discount}")
            lines.append(f"   ⭐ Rating: {offer.rating}")
            lines.append(f"   🔗 [View Product]({offer.url})")
            lines.append("")

    if data.summary:
        lines.append(f"📝 *Summary:* {data.summary}")

    return "\n".join(lines)


def _format_generic_model(data: dict, model_name: str) -> str:
    """Format a generic Pydantic model for display."""
    lines = [f"📋 *{model_name}*", ""]

    for key, value in data.items():
        if value is None:
            continue

        formatted_key = key.replace("_", " ").title()

        if isinstance(value, list):
            lines.append(f"*{formatted_key}:*")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"  • {json.dumps(item, indent=2)}")
                else:
                    lines.append(f"  • {item}")
        elif isinstance(value, dict):
            lines.append(f"*{formatted_key}:*")
            lines.append(f"```json\n{json.dumps(value, indent=2)}\n```")
        else:
            lines.append(f"*{formatted_key}:* {value}")

    return "\n".join(lines)


def convert_markdown_to_telegram(text: str) -> str:
    """
    Convert common markdown patterns to Telegram Markdown v1 compatible format.

    Simple conversions:
    - ## Headers -> *Bold text* with newlines
    - **bold** -> *bold*
    - Remove > quote markers
    """
    if not text:
        return text

    # Convert headers (## Header -> *Header* with extra newline)
    text = re.sub(r"^##\s+(.+)$", r"*\1*\n", text, flags=re.MULTILINE)

    # Convert **bold** to *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Remove > quote markers at start of lines
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)

    return text


def clean_ai_response(response: Union[str, BaseModel]) -> str:
    """
    Clean and format AI response for user display.

    Handles both text responses and structured Pydantic model responses.
    """
    try:
        if isinstance(response, BaseModel):
            if isinstance(response, ProductSearchResult):
                return _format_product_search_result(response)
            else:
                data = response.model_dump()
                return _format_generic_model(data, response.__class__.__name__)

        # Handle string responses (existing logic)
        if not isinstance(response, str):
            response = str(response)

        lines = response.splitlines()
        # Remove the first and last lines if they are code block markers
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
            lines = lines[1:-1]
        # remove the leading - if this is a list
        if len(lines) > 0:
            lines[0] = lines[0].strip().lstrip("-").strip()

        cleaned = "\n".join(lines)

        # Convert markdown to Telegram-compatible format
        cleaned = convert_markdown_to_telegram(cleaned)

        return cleaned

    except Exception as e:
        logger.error(f"Error formatting AI response: {e}")
        return str(response)


def escape_markdown_v1(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV1.

    MarkdownV1 special characters that need escaping:
    * _ ` [

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for Telegram MarkdownV1
    """
    if not text:
        return text

    # Escape special markdown characters
    special_chars = ["*", "_", "`", "["]
    for char in special_chars:
        text = text.replace(char, f"\\{char}")

    return text


def _is_section_header(line: str) -> bool:
    """Check if a line is a section header (bold text like *Header*)."""
    stripped = line.strip()
    return stripped.startswith("*") and stripped.endswith("*") and len(stripped) > 2


def _split_text_into_chunks(text: str, max_length: int) -> list[str]:
    """
    Split text into chunks, preserving structure where possible.
    Prefers to split at section boundaries (bold headers).
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = ""

    for i, line in enumerate(lines):
        potential_length = len(current_chunk) + len(line) + 1

        # If adding this line would exceed max_length
        if potential_length > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = line
            else:
                # Line itself is too long
                chunks.extend(_split_long_line(line, max_length))
        # If we're getting close to max_length (80%) and next line is a section header, split here
        elif potential_length > max_length * 0.8 and i + 1 < len(lines) and _is_section_header(lines[i + 1]):
            current_chunk = current_chunk + "\n" + line if current_chunk else line
            chunks.append(current_chunk.strip())
            current_chunk = ""
        else:
            current_chunk = current_chunk + "\n" + line if current_chunk else line

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def _split_long_line(line: str, max_length: int) -> list[str]:
    """Split a single long line into chunks."""
    chunks = []
    words = line.split(" ")
    current_line = ""

    for word in words:
        if len(current_line) + len(word) + 1 > max_length:
            if current_line:
                chunks.append(current_line.strip())
                current_line = word
            else:
                chunks.append(word[:max_length])
                current_line = word[max_length:]
        else:
            current_line = current_line + " " + word if current_line else word

    if current_line:
        chunks.append(current_line)

    return chunks


async def _send_single_chunk(bot: Bot, chat_id: int, chunk: str) -> None:
    """Send a single chunk, trying markdown first then plain text."""
    try:
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        logger.warning(f"Failed to send message as markdown: {e}, trying plain text")
        try:
            await bot.send_message(chat_id=chat_id, text=chunk)
        except TelegramError as e:
            logger.error(f"Failed to send message even as plain text: {e}")


async def send_message_chunks(bot: Bot, chat_id: int, text: str, max_length: int = 4096) -> None:
    """
    Send a message, splitting it into chunks if too long.
    First tries to send as markdown, falls back to plain text if that fails.

    Args:
        bot: Telegram bot instance
        chat_id: Chat ID to send message to
        text: Text to send
        max_length: Maximum length of each chunk (default 4096)
    """
    if not text.strip():
        return

    chunks = _split_text_into_chunks(text, max_length)

    for chunk in chunks:
        if chunk.strip():
            await _send_single_chunk(bot, chat_id, chunk)
