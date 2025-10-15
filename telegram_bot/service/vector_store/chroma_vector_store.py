from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Mapping

from chromadb import PersistentClient
from chromadb.config import Settings

from telegram_bot.config import ChromaVectorStoreConfig
from telegram_bot.service.vector_store.protocols import VectorDocument, VectorMatch, VectorStoreProtocol


class ChromaVectorStore(VectorStoreProtocol):
    def __init__(
        self,
        config: ChromaVectorStoreConfig,
        embedding_function: Any,
        out_dir: Path,
        *,
        client: PersistentClient | None = None,
    ) -> None:
        self._config = config
        self._embedding_function = embedding_function
        self._persist_path = config.resolve_persist_path(out_dir)
        self._client = client or self._create_client(self._persist_path)
        self._collection = self._client.get_or_create_collection(
            name=self._config.collection_name,
            embedding_function=self._embedding_function,
        )

    @property
    def collection(self):
        return self._collection

    def upsert(self, documents: Sequence[VectorDocument]) -> None:
        if not documents:
            return

        ids = [doc.id for doc in documents]
        texts = [doc.content for doc in documents]
        metadatas = [dict(doc.metadata) for doc in documents]

        self._collection.upsert(ids=ids, documents=texts, metadatas=metadatas)

    def delete_missing(self, valid_ids: Iterable[str]) -> None:
        valid_set = set(valid_ids)
        existing = self._collection.get() or {}
        existing_ids = existing.get("ids", [])

        if not existing_ids:
            return

        stale_ids = [doc_id for doc_id in existing_ids if doc_id not in valid_set]
        if stale_ids:
            self._collection.delete(ids=stale_ids)

    def query(
        self,
        query_text: str,
        limit: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> Sequence[VectorMatch]:
        response = self._collection.query(
            query_texts=[query_text],
            n_results=limit,
            where=where,
            include=["metadatas", "documents", "distances"],
        )

        ids = self._first_or_empty(response.get("ids"))
        distances = self._first_or_empty(response.get("distances"))
        documents = self._first_or_empty(response.get("documents"))
        metadatas = self._first_or_empty(response.get("metadatas"))

        matches: list[VectorMatch] = []
        for doc_id, distance, document, metadata in zip(ids, distances, documents, metadatas, strict=True):
            # ChromaDB returns L2 distances (lower is better)
            # Convert to similarity score (higher is better) by inverting
            # Using 1/(1+distance) to map distances to [0,1] range
            similarity = 1.0 / (1.0 + float(distance))
            matches.append(
                VectorMatch(
                    id=doc_id,
                    score=similarity,
                    content=document,
                    metadata=metadata or {},
                )
            )
        return matches

    def _create_client(self, persist_path: Path) -> PersistentClient:
        settings = Settings(persist_directory=str(persist_path))
        return PersistentClient(settings=settings)

    @staticmethod
    def _first_or_empty(values: Sequence[Any] | None) -> Sequence[Any]:
        if not values:
            return []
        return values[0] if isinstance(values[0], (list, tuple)) else values
