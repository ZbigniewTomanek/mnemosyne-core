from __future__ import annotations

from datetime import date

from telegram_bot.service.persistent_memory.document import PersistentMemoryDelta
from telegram_bot.service.persistent_memory.llm_models import PersistentMemoryLLMResponse


def test_llm_response_converts_to_domain_deltas() -> None:
    payload = {
        "sections": [
            {
                "name": "Zdrowie i Samopoczucie",
                "add": [
                    {
                        "statement": "Meditates every morning",
                        "category": "routine",
                        "confidence": 0.8,
                        "sources": ["note-2024-04-25"],
                    }
                ],
                "update": [
                    {
                        "id": "health-1",
                        "statement": "Maintains hydration habit",
                        "category": "habit",
                        "confidence": 0.95,
                        "first_seen": "2024-04-01",
                        "last_seen": "2024-04-20",
                        "sources": ["note-2024-04-15", "note-2024-04-20"],
                    }
                ],
                "remove": ["health-3"],
            }
        ]
    }

    response = PersistentMemoryLLMResponse.model_validate(payload)
    deltas = response.to_domain_deltas()

    assert isinstance(deltas, dict)
    assert "Zdrowie i Samopoczucie" in deltas

    section_delta = deltas["Zdrowie i Samopoczucie"]
    assert isinstance(section_delta, PersistentMemoryDelta)
    assert len(section_delta.additions) == 1
    assert section_delta.additions[0].id == ""
    assert section_delta.additions[0].statement == "Meditates every morning"
    assert section_delta.additions[0].sources == ("note-2024-04-25",)

    updated_fact = section_delta.updates[0]
    assert updated_fact.id == "health-1"
    assert updated_fact.first_seen == date(2024, 4, 1)
    assert section_delta.removals == ("health-3",)
