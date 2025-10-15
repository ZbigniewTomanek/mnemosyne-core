from __future__ import annotations

from typing import TYPE_CHECKING

from agents import function_tool

from telegram_bot.service.vector_store.protocols import VectorMatch

if TYPE_CHECKING:
    from telegram_bot.service.obsidian.obsidian_embedding_service import ObsidianEmbeddingIndexer


MAX_SNIPPET_LENGTH = 500


def _format_match(match: VectorMatch) -> str:
    path = match.metadata.get("relative_path") if isinstance(match.metadata, dict) else None
    path = path or match.id
    snippet = match.content.replace("\n", " ").strip()
    if len(snippet) > MAX_SNIPPET_LENGTH:
        snippet = snippet[: MAX_SNIPPET_LENGTH - 3].rstrip() + "…"
    return f"- {path} (distance: {match.score:.2f})\n  {snippet}"


def create_semantic_search_tool(indexer: "ObsidianEmbeddingIndexer"):
    """Create a function tool that performs semantic search over Obsidian notes."""

    async def _semantic_search(query: str, limit: int = 5, path_filter: str | None = None) -> str:
        """Search Obsidian notes semantically and return top matches.

        Args:
            query: Natural language query describing the desired information.
            limit: Maximum number of results to return (default: 5).
            path_filter: Optional relative path filter to limit matches to a specific note or folder.

        Returns:
            A formatted string listing matched notes with similarity scores and snippets.
        """

        matches = await indexer.semantic_search(query, limit=limit, path_filter=path_filter)
        if not matches:
            return "No matching notes found."
        lines = ["*Semantic matches:*"]
        lines.extend(_format_match(match) for match in matches)
        return "\n".join(lines)

    tool = function_tool(_semantic_search)
    tool.python_callable = _semantic_search  # type: ignore[attr-defined]
    return tool
