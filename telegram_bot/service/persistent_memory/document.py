from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

import yaml

from .models import PersistentFact, PersistentMemorySection

SECTION_ORDER: tuple[str, ...] = (
    "Zdrowie i Samopoczucie",
    "Praca i Produktywność",
    "Relacje i Kontakty",
    "Hobby i Zainteresowania",
    "Projekty Osobiste",
    "Finanse",
    "Systemy i Narzędzia",
    "Podróże",
)


@dataclass(slots=True)
class PersistentMemoryDocument:
    """Aggregate root for the persistent memory Markdown document."""

    frontmatter: Mapping[str, object]
    sections: Sequence[PersistentMemorySection]

    @classmethod
    def parse(cls, markdown: str) -> PersistentMemoryDocument:
        """Parse Markdown into a structured persistent memory document."""
        raw = markdown or ""
        lines = raw.splitlines()
        frontmatter: Mapping[str, object] = {}
        body_lines = lines

        if lines and lines[0].strip() == "---":
            closing_index = None
            for index, value in enumerate(lines[1:], start=1):
                if value.strip() == "---":
                    closing_index = index
                    break
            if closing_index is None:
                raise ValueError("Frontmatter opening delimiter found without closing delimiter")
            yaml_text = "\n".join(lines[1:closing_index])
            loaded = yaml.safe_load(yaml_text) or {}
            if not isinstance(loaded, Mapping):
                raise ValueError("Frontmatter must deserialize into a mapping")
            sanitized: dict[str, object] = {}
            for key, value in loaded.items():
                if isinstance(value, date):
                    sanitized[key] = value.isoformat()
                else:
                    sanitized[key] = value
            frontmatter = sanitized
            body_lines = lines[closing_index + 1 :]

        body = "\n".join(body_lines).strip("\n")

        sections: list[PersistentMemorySection] = []
        if body:
            current_name: str | None = None
            current_buffer: list[str] = []
            for line in body.splitlines():
                if line.startswith("## "):
                    if current_name is not None:
                        section_text = "\n".join(current_buffer)
                        sections.append(PersistentMemorySection.parse(current_name, section_text))
                    current_name = line.removeprefix("## ").strip()
                    current_buffer = []
                else:
                    current_buffer.append(line)
            if current_name is not None:
                section_text = "\n".join(current_buffer)
                sections.append(PersistentMemorySection.parse(current_name, section_text))

        return cls(frontmatter=frontmatter, sections=tuple(sections))

    def render(self) -> str:
        """Render the document back into Markdown with sections."""
        lines: list[str] = []
        if self.frontmatter:
            frontmatter_block = _render_frontmatter(self.frontmatter)
            lines.append(frontmatter_block)
        section_lookup = {section.name: section for section in self.sections}
        ordered_sections = [section_lookup[name] for name in SECTION_ORDER if name in section_lookup]
        remaining = [section for section in self.sections if section.name not in SECTION_ORDER]
        full_order = ordered_sections + remaining
        if full_order:
            if lines:
                lines.append("")
            section_blocks = []
            for section in full_order:
                rendered_section = section.render()
                block_lines = [f"## {section.name}", "", rendered_section]
                section_blocks.append("\n".join(block_lines))
            lines.append("\n\n".join(section_blocks))
        rendered = "\n".join(lines)
        return rendered if rendered.endswith("\n") else f"{rendered}\n"

    def with_updated_section(self, section: PersistentMemorySection) -> PersistentMemoryDocument:
        """Return a copy of the document with the given section replaced."""
        updated_sections = []
        replaced = False
        for existing in self.sections:
            if existing.name == section.name:
                updated_sections.append(section)
                replaced = True
            else:
                updated_sections.append(existing)
        if not replaced:
            updated_sections.append(section)
        return replace(self, sections=tuple(updated_sections))

    def apply_changes(
        self,
        section_deltas: Mapping[str, "PersistentMemoryDelta"],
    ) -> PersistentMemoryDocument:
        """Apply per-section deltas to produce a new document state."""
        section_map = {section.name: section for section in self.sections}
        for name, delta in section_deltas.items():
            existing_section = section_map.get(name, PersistentMemorySection(name, []))
            updated_section = existing_section.diff(
                additions=delta.additions,
                updates=delta.updates,
                removals=delta.removals,
            )
            section_map[name] = updated_section
        ordered_sections = []
        for section_name in SECTION_ORDER:
            if section_name in section_map:
                ordered_sections.append(section_map.pop(section_name))
        ordered_sections.extend(section_map.values())
        return replace(self, sections=tuple(ordered_sections))


@dataclass(slots=True)
class PersistentMemoryDelta:
    """Delta describing add/update/remove operations for a section."""

    additions: tuple[PersistentFact, ...]
    updates: tuple[PersistentFact, ...]
    removals: tuple[str, ...]

    @classmethod
    def empty(cls) -> PersistentMemoryDelta:
        return cls((), (), ())


def _render_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _render_frontmatter(frontmatter: Mapping[str, object]) -> str:
    def render_value(key: str, value: object, indent: int, output: list[str]) -> None:
        prefix = " " * indent
        if isinstance(value, Mapping):
            output.append(f"{prefix}{key}:")
            for nested_key, nested_value in value.items():
                render_value(str(nested_key), nested_value, indent + 2, output)
        elif isinstance(value, (list, tuple)):
            output.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, (Mapping, list, tuple)):
                    raise ValueError("Nested collection items are not supported in frontmatter")
                output.append(f"{prefix}- {_render_scalar(item)}")
        else:
            output.append(f"{prefix}{key}: {_render_scalar(value)}")

    lines: list[str] = ["---"]
    for key, value in frontmatter.items():
        render_value(str(key), value, 0, lines)
    lines.append("---")
    return "\n".join(lines)
