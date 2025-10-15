from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, Field

from .document import PersistentMemoryDelta
from .models import PersistentFact


class FactDeltaPayload(BaseModel):
    """Pydantic model describing a fact delta entry returned by the LLM."""

    statement: str
    category: str
    id: str | None = None
    confidence: float | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    sources: list[str] = Field(default_factory=list)
    status: str | None = None
    notes: str | None = None

    def to_domain_fact(self) -> PersistentFact:
        """Convert this payload into a domain PersistentFact."""
        return PersistentFact.from_llm_payload(
            id=self.id or "",
            statement=self.statement,
            category=self.category,
            confidence=self.confidence,
            first_seen=self.first_seen,
            last_seen=self.last_seen,
            sources=self.sources,
            status=self.status,
            notes=self.notes,
        )


class SectionDeltaPayload(BaseModel):
    """Structured delta for a single persistent memory section."""

    name: str
    add: list[FactDeltaPayload] = Field(default_factory=list)
    update: list[FactDeltaPayload] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)

    def to_domain_delta(self) -> PersistentMemoryDelta:
        additions = tuple(item.to_domain_fact() for item in self.add)
        updates = tuple(item.to_domain_fact() for item in self.update)
        removals = tuple(identifier for identifier in self.remove)
        return PersistentMemoryDelta(additions=additions, updates=updates, removals=removals)


class PersistentMemoryLLMResponse(BaseModel):
    """Top-level structured response containing per-section deltas."""

    sections: list[SectionDeltaPayload] = Field(default_factory=list)

    def to_domain_deltas(self) -> Mapping[str, PersistentMemoryDelta]:
        return {section.name: section.to_domain_delta() for section in self.sections}
