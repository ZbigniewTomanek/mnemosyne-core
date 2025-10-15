"""Service layer for orchestrating persistent memory updates.

This module provides:
- PersistentMemoryRepository: Protocol for storage abstraction
- PersistentMemoryUpdater: Core service handling read → diff → write workflow
- SectionRoutingConfig: Declarative mapping from fact categories to sections

The updater generates deterministic IDs, routes facts to appropriate sections,
and maintains observable update summaries for debugging and monitoring.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from .document import SECTION_ORDER, PersistentMemoryDelta, PersistentMemoryDocument
from .models import PersistentFact


class PersistentMemoryRepository(Protocol):
    """Abstract repository for persistent memory document I/O."""

    async def load(self) -> str:  # pragma: no cover - interface only
        ...

    async def save(self, content: str) -> None:  # pragma: no cover - interface only
        ...


@dataclass(slots=True)
class SectionRoutingConfig:
    """Configuration determining section routing rules."""

    category_to_section: Mapping[str, str]
    default_section: str


@dataclass(slots=True)
class PersistentMemoryUpdater:
    """Core service orchestrating persistent memory updates."""

    repository: PersistentMemoryRepository
    routing: SectionRoutingConfig
    now_factory: Callable[[], datetime] = datetime.now
    last_summary: dict[str, dict[str, int]] = field(init=False, default_factory=dict)

    async def update(
        self,
        deltas: Mapping[str, PersistentMemoryDelta],
    ) -> PersistentMemoryDocument:
        """Update persistent memory based on LLM-provided deltas."""
        self.last_summary = {}

        raw_document = await self.repository.load()
        document = (
            PersistentMemoryDocument.parse(raw_document)
            if raw_document.strip()
            else PersistentMemoryDocument(frontmatter={}, sections=())
        )
        today = self.now_factory().date()

        fact_section_index = {
            fact.id: section.name for section in document.sections for fact in section.facts if fact.id
        }

        existing_ids = {fact.id for section in document.sections for fact in section.facts if fact.id}

        aggregated_additions: dict[str, list[PersistentFact]] = {}
        aggregated_updates: dict[str, list[PersistentFact]] = {}
        aggregated_removals: dict[str, list[str]] = {}
        for section_name, delta in deltas.items():
            target_section = self._resolve_section_name(section_name, delta, fact_section_index)

            additions = []
            for fact in delta.additions:
                identifier = fact.id or self._generate_fact_id(fact, existing_ids)
                existing_ids.add(identifier)
                additions.append(
                    replace(
                        fact,
                        id=identifier,
                        first_seen=fact.first_seen or today,
                        last_seen=fact.last_seen or today,
                    )
                )
            updates = []
            for fact in delta.updates:
                identifier = fact.id or self._generate_fact_id(fact, existing_ids)
                existing_ids.add(identifier)
                updates.append(
                    replace(
                        fact,
                        id=identifier,
                        last_seen=fact.last_seen or today,
                    )
                )
            aggregated_additions.setdefault(target_section, []).extend(additions)
            aggregated_updates.setdefault(target_section, []).extend(updates)
            aggregated_removals.setdefault(target_section, []).extend(delta.removals)

        processed: dict[str, PersistentMemoryDelta] = {}
        for section_name in set(
            list(aggregated_additions.keys()) + list(aggregated_updates.keys()) + list(aggregated_removals.keys())
        ):
            removals = tuple(dict.fromkeys(aggregated_removals.get(section_name, [])))
            processed[section_name] = PersistentMemoryDelta(
                additions=tuple(aggregated_additions.get(section_name, [])),
                updates=tuple(aggregated_updates.get(section_name, [])),
                removals=removals,
            )

        self.last_summary = {
            name: {
                "add": len(delta.additions),
                "update": len(delta.updates),
                "remove": len(delta.removals),
            }
            for name, delta in processed.items()
        }

        updated_document = document.apply_changes(processed)
        frontmatter = dict(updated_document.frontmatter)
        frontmatter.setdefault("consolidation_type", "persistent")
        frontmatter["last_updated"] = today.isoformat()
        frontmatter.setdefault("tags", ["ai_memory", "persistent_facts"])
        final_document = replace(updated_document, frontmatter=frontmatter)

        await self.repository.save(final_document.render())
        return final_document

    def _resolve_section_name(
        self,
        section_name: str,
        delta: PersistentMemoryDelta,
        fact_section_index: Mapping[str, str],
    ) -> str:
        normalized = section_name.strip()
        if normalized in SECTION_ORDER:
            return normalized

        for fact in delta.updates:
            if fact.id and fact.id in fact_section_index:
                return fact_section_index[fact.id]

        for removal_id in delta.removals:
            if removal_id in fact_section_index:
                return fact_section_index[removal_id]

        for fact in (*delta.additions, *delta.updates):
            mapped = self.routing.category_to_section.get(fact.category)
            if mapped:
                return mapped

        return self.routing.default_section

    @staticmethod
    def _generate_fact_id(fact: PersistentFact, existing: set[str]) -> str:
        source_text = f"{fact.category}|{fact.statement}".lower().strip()
        digest = hashlib.sha1(source_text.encode("utf-8")).hexdigest()
        prefix_source = fact.category or "fact"
        prefix = re.sub(r"[^a-z0-9]+", "-", prefix_source.lower()).strip("-") or "fact"
        base = f"{prefix}-{digest[:8]}"
        candidate = base
        suffix = 1
        while candidate in existing:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate


@dataclass(slots=True)
class FileSystemPersistentMemoryRepository:
    """Repository that uses asynchronous file access for persistence."""

    loader: Callable[[], Awaitable[str]]
    saver: Callable[[str], Awaitable[None]]

    async def load(self) -> str:
        return await self.loader()

    async def save(self, content: str) -> None:
        await self.saver(content)
