from __future__ import annotations

import pytest


@pytest.fixture
def sample_document_markdown() -> str:
    return (
        "---\n"
        "consolidation_type: persistent\n"
        "last_updated: 2024-05-01\n"
        "tags:\n"
        "- ai_memory\n"
        "- persistent_facts\n"
        "---\n\n"
        "## Zdrowie i Samopoczucie\n\n"
        "| id | statement | category | confidence | first_seen | last_seen | sources | status | notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| health-1 | Drinks two liters of water daily | habit | 0.9 | 2024-04-01 | 2024-04-15 | note-2024-04-15 | active | |\n\n"  # noqa: E501
        "## Praca i Produktywność\n\n"
        "| id | statement | category | confidence | first_seen | last_seen | sources | status | notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| work-1 | Prefers async collaboration | preference |  | 2024-03-01 | 2024-03-10 | weekly-2024-10 | active | keep meetings short |\n"  # noqa: E501
    )
