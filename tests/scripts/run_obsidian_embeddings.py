from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from telegram_bot.config import BotSettings
from telegram_bot.service.obsidian.obsidian_embedding_service import EmbeddingRefreshStats
from telegram_bot.service.vector_store.protocols import VectorMatch
from telegram_bot.service_factory import ServiceFactory


def build_service_factory() -> ServiceFactory:
    """Instantiate the shared ServiceFactory using environment-backed settings."""
    return ServiceFactory(BotSettings())


def _run(coro):
    return asyncio.run(coro)


def _format_stats(stats: EmbeddingRefreshStats) -> str:
    return (
        f"Processed files: {stats.processed_files}\n"
        f"Skipped files: {stats.skipped_files}\n"
        f"Deleted files: {stats.deleted_files}\n"
        f"Upserted chunks: {stats.upserted_chunks}\n"
    )


def _format_matches(matches: Sequence[VectorMatch]) -> str:
    if not matches:
        return "No results found."

    rendered: list[str] = []
    for match in matches:
        metadata = match.metadata if isinstance(match.metadata, dict) else {}
        path = metadata.get("relative_path", match.id)
        snippet = match.content.replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:197].rstrip() + "…"
        rendered.append(f"{path} (score {match.score:.2f})\n  {snippet}")
    return "\n".join(rendered)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage Obsidian embedding index")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("refresh", help="Run incremental refresh of Obsidian embeddings")
    subparsers.add_parser("rebuild", help="Rebuild embeddings from scratch")

    query_parser = subparsers.add_parser("query", help="Run a semantic search query")
    query_parser.add_argument("--text", required=True, help="Search query text")
    query_parser.add_argument("--limit", type=int, default=5, help="Maximum number of matches to return")
    query_parser.add_argument(
        "--path-prefix",
        dest="path_prefix",
        default=None,
        help="Optional relative path filter",
    )

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    factory = build_service_factory()
    indexer = factory.obsidian_embedding_indexer

    if args.command == "refresh":
        stats = _run(indexer.refresh_incremental())
        print(_format_stats(stats))
        return 0

    if args.command == "rebuild":
        stats = _run(indexer.refresh_full())
        print(_format_stats(stats))
        return 0

    if args.command == "query":
        matches = _run(indexer.semantic_search(args.text, limit=args.limit, path_filter=args.path_prefix))
        print(_format_matches(matches))
        return 0

    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
