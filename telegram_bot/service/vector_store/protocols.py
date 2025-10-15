from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class VectorDocument:
    id: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    """Represents a vector similarity search result.

    Attributes:
        id: Unique identifier for the matched document.
        score: Distance metric where lower values indicate better matches (0.0 = perfect match).
        content: The text content of the matched document.
        metadata: Additional metadata associated with the document.
    """

    id: str
    score: float
    content: str
    metadata: Mapping[str, Any]


class VectorStoreProtocol(Protocol):
    def upsert(self, documents: Sequence[VectorDocument]) -> None:
        """Add or update the vector representations for the supplied documents."""

    def delete_missing(self, valid_ids: Iterable[str]) -> None:
        """Remove any vectors whose ids are not present in ``valid_ids``."""

    def query(
        self,
        query_text: str,
        limit: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> Sequence[VectorMatch]:
        """Return the best-matching vectors for the supplied query text."""
