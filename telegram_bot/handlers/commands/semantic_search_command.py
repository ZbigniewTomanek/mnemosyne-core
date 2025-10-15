from __future__ import annotations

from urllib.parse import quote

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.obsidian.obsidian_embedding_service import ObsidianEmbeddingIndexer
from telegram_bot.utils import escape_markdown_v1


class SearchObsidianHandler(PrivateHandler):
    def __init__(self, indexer: ObsidianEmbeddingIndexer, vault_name: str, max_snippet_length: int = 300) -> None:
        super().__init__()
        self.indexer = indexer
        self.max_snippet_length = max_snippet_length
        self.vault_name = vault_name

    def _format_obsidian_url(self, relative_path: str) -> str:
        """Generate Obsidian protocol URL for a given note path."""
        encoded_path = quote(relative_path, safe="")
        return f"obsidian://open?vault={self.vault_name}&file={encoded_path}"

    def _extract_match_details(self, match) -> tuple[str, str, str]:
        """Collect searchable metadata and a cleaned preview snippet."""
        path = match.metadata.get("relative_path") if isinstance(match.metadata, dict) else None
        path = path or match.id

        display_name = path[:-3] if path.endswith(".md") else path
        obsidian_url = self._format_obsidian_url(path)

        raw_content = getattr(match, "content", "") or ""
        snippet = raw_content.replace("\n", " ").strip()
        if len(snippet) > self.max_snippet_length:
            snippet = snippet[: self.max_snippet_length - 3].rstrip() + "…"

        return display_name, obsidian_url, snippet

    def _format_match_markdown(self, match, index: int) -> str:
        display_name, obsidian_url, snippet = self._extract_match_details(match)
        safe_display = escape_markdown_v1(display_name)
        safe_snippet = escape_markdown_v1(snippet) if snippet else ""

        lines = [f"{index}. [{safe_display}]({obsidian_url})", f"   • Score: {match.score:.3f}"]
        if safe_snippet:
            lines.append(f"   • {safe_snippet}")
        return "\n".join(lines)

    def _format_match_plain(self, match, index: int) -> str:
        display_name, obsidian_url, snippet = self._extract_match_details(match)
        lines = [
            f"{index}. {display_name}",
            f"   • Score: {match.score:.3f}",
            f"   • Open in Obsidian: {obsidian_url}",
        ]
        if snippet:
            lines.append(f"   • {snippet}")
        return "\n".join(lines)

    def _build_markdown_response(self, query: str, matches) -> str:
        safe_query = escape_markdown_v1(query)
        lines = ["🔍 *Search results*", f"• Query: {safe_query}"]
        for idx, match in enumerate(matches, start=1):
            lines.append("")
            lines.append(self._format_match_markdown(match, idx))
        return "\n".join(lines)

    def _build_plain_response(self, query: str, matches) -> str:
        lines = ["Search results", f"Query: {query}"]
        for idx, match in enumerate(matches, start=1):
            lines.append("")
            lines.append(self._format_match_plain(match, idx))
        return "\n".join(lines)

    async def _handle(self, update: Update, context: CallbackContext) -> None:
        # Check if query is provided
        if not context.args:
            await update.message.reply_text(
                "❓ *Usage:* `/search_obsidian <query>`\n\n"
                "Search your Obsidian notes semantically.\n\n"
                "*Example:*\n"
                "`/search_obsidian machine learning concepts`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Join all arguments to form the query
        query = " ".join(context.args)

        # Show typing indicator while searching
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # Perform semantic search
        try:
            matches = await self.indexer.semantic_search(query, limit=5)
        except Exception as exc:
            error_text = escape_markdown_v1(str(exc)) if str(exc) else "Unknown error"
            message = (
                "❌ *Search failed:* " f"{error_text}\n\nPlease try again or contact support if the issue persists."
            )
            try:
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            except Exception as send_exc:  # pragma: no cover - network interaction
                logger.error("Failed to send markdown search failure message: %s", send_exc)
                fallback = (
                    "Search failed. " f"Error: {str(exc)}. Please try again or contact support if the issue persists."
                )
                await update.message.reply_text(fallback)
            return

        # Format and send results
        if not matches:
            safe_query = escape_markdown_v1(query)
            message = (
                "🔍 *No results found.*\n"
                f"• Query: {safe_query}\n"
                "• Try rephrasing your query or using different keywords."
            )
            try:
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            except Exception as send_exc:  # pragma: no cover - network interaction
                logger.error("Failed to send markdown no-results message: %s", send_exc)
                fallback = (
                    "No results found. " f"Query: {query}. Try rephrasing your query or using different keywords."
                )
                await update.message.reply_text(fallback)
            return

        # Build response with clickable links
        response_markdown = self._build_markdown_response(query, matches)
        try:
            await update.message.reply_text(
                response_markdown,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        except Exception as exc:  # pragma: no cover - network interaction
            logger.error("Failed to send markdown search results: %s", exc)
            response_plain = self._build_plain_response(query, matches)
            await update.message.reply_text(
                response_plain,
                disable_web_page_preview=True,
            )


def get_search_obsidian_command(
    indexer: ObsidianEmbeddingIndexer, vault_name: str, max_snippet_length: int = 300
) -> CommandHandler:
    return CommandHandler("search_obsidian", SearchObsidianHandler(indexer, vault_name, max_snippet_length).handle)
