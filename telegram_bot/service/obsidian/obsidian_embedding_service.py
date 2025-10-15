from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from telegram_bot.service.vector_store.protocols import VectorDocument, VectorMatch, VectorStoreProtocol

if TYPE_CHECKING:
    from telegram_bot.config import ChromaVectorStoreConfig

_STATE_FILENAME = "chroma_index_state.json"


@dataclass
class EmbeddingRefreshStats:
    processed_files: int
    skipped_files: int
    deleted_files: int
    upserted_chunks: int


class ObsidianEmbeddingIndexer:
    def __init__(
        self,
        obsidian_service: Any,
        vector_store: VectorStoreProtocol,
        config: "ChromaVectorStoreConfig",
        out_dir: Path,
        text_splitter: Any | None = None,
        state_path: Path | None = None,
    ) -> None:
        self._obsidian_service = obsidian_service
        self._vector_store = vector_store
        self._config = config
        self._out_dir = Path(out_dir)
        self._state_path = state_path or (self._out_dir / _STATE_FILENAME)
        self._text_splitter = text_splitter or self._build_text_splitter(config)

    async def refresh_incremental(self) -> EmbeddingRefreshStats:
        logger.info("Starting Obsidian embedding refresh")
        previous_state = self._load_state()
        previous_files: Mapping[str, Mapping[str, Any]] = previous_state.get("files", {})
        current_state: dict[str, dict[str, Any]] = {}

        processed_files = 0
        skipped_files = 0
        upserted_chunks = 0

        documents_to_upsert: list[VectorDocument] = []
        valid_ids: set[str] = set()

        deleted_candidates = set(previous_files.keys())

        for file_path in self._iter_markdown_files():
            relative_path = file_path.relative_to(self._vault_root).as_posix()
            file_stats = file_path.stat()
            checksum = self._compute_checksum(file_stats)
            mtime_iso = datetime.fromtimestamp(file_stats.st_mtime, tz=timezone.utc).isoformat()

            previous_entry = previous_files.get(relative_path)
            if previous_entry and previous_entry.get("checksum") == checksum and previous_entry.get("doc_ids"):
                skipped_files += 1
                doc_ids = previous_entry.get("doc_ids", [])
                valid_ids.update(doc_ids)
                current_state[relative_path] = dict(previous_entry)
                deleted_candidates.discard(relative_path)
                continue

            content = await self._obsidian_service.safe_read_file(relative_path)
            title = self._extract_title(content, relative_path)
            chunks = self._split_content(content)

            doc_ids: list[str] = []
            for index, chunk in enumerate(chunks):
                doc_id = self._build_document_id(relative_path, index)
                metadata = {
                    "relative_path": relative_path,
                    "chunk_index": index,
                    "checksum": checksum,
                    "mtime": mtime_iso,
                    "title": title,
                }
                metadata.update(getattr(chunk, "metadata", {}) or {})
                document = VectorDocument(id=doc_id, content=getattr(chunk, "page_content", ""), metadata=metadata)
                doc_ids.append(doc_id)
                documents_to_upsert.append(document)
            processed_files += 1
            upserted_chunks += len(doc_ids)
            valid_ids.update(doc_ids)
            current_state[relative_path] = {
                "checksum": checksum,
                "mtime": mtime_iso,
                "doc_ids": doc_ids,
                "title": title,
            }
            deleted_candidates.discard(relative_path)

        deleted_files = len(deleted_candidates)

        if documents_to_upsert:
            for batch in self._batch_documents(documents_to_upsert, self._config.embedding_batch_size):
                self._vector_store.upsert(batch)

        self._vector_store.delete_missing(valid_ids)
        self._save_state({"files": current_state})
        logger.info(
            "Completed Obsidian embedding refresh: processed=%d skipped=%d deleted=%d chunks=%d",
            processed_files,
            skipped_files,
            deleted_files,
            upserted_chunks,
        )
        return EmbeddingRefreshStats(
            processed_files=processed_files,
            skipped_files=skipped_files,
            deleted_files=deleted_files,
            upserted_chunks=upserted_chunks,
        )

    async def refresh_full(self) -> EmbeddingRefreshStats:
        self._save_state({"files": {}})
        return await self.refresh_incremental()

    async def semantic_search(
        self,
        query: str,
        *,
        limit: int = 5,
        path_filter: str | None = None,
    ) -> Sequence[VectorMatch]:
        where = {"relative_path": path_filter} if path_filter else None
        return self._vector_store.query(query, limit=limit, where=where)

    @property
    def _vault_root(self) -> Path:
        return Path(self._obsidian_service.config.obsidian_root_dir)

    def _iter_markdown_files(self) -> Sequence[Path]:
        return [path for path in self._vault_root.rglob("*.md") if path.is_file()]

    @staticmethod
    def _compute_checksum(stat_result) -> str:
        return f"{stat_result.st_mtime_ns}-{stat_result.st_size}"

    def _split_content(self, content: str):
        return self._text_splitter.create_documents([content], metadatas=[{}])

    @staticmethod
    def _extract_title(content: str, relative_path: str) -> str:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped:
                if stripped.startswith("#"):
                    return stripped.lstrip("# ").strip()
                return stripped
        return Path(relative_path).stem.replace("-", " ").title()

    @staticmethod
    def _build_document_id(relative_path: str, index: int) -> str:
        return f"{relative_path}::chunk-{index}"

    @staticmethod
    def _batch_documents(documents: Sequence[VectorDocument], batch_size: int) -> Iterable[Sequence[VectorDocument]]:
        if batch_size <= 0:
            yield documents
            return
        for start in range(0, len(documents), batch_size):
            yield documents[start : start + batch_size]

    def _load_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return {"files": {}}
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load index state from %s: %s", self._state_path, exc)
            return {"files": {}}

    def _save_state(self, data: Mapping[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _build_text_splitter(config: "ChromaVectorStoreConfig"):
        return RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
