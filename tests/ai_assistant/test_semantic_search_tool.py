from __future__ import annotations

import pytest

from telegram_bot.ai_assistant.tools.semantic_search_tool import create_semantic_search_tool
from telegram_bot.service.vector_store.protocols import VectorMatch


class StubIndexer:
    def __init__(self):
        self.calls = []

    async def semantic_search(self, query: str, *, limit: int = 5, path_filter: str | None = None):
        self.calls.append((query, limit, path_filter))
        return [
            VectorMatch(id="note1::0", score=0.12, content="Chunk text", metadata={"relative_path": "note1.md"}),
            VectorMatch(
                id="note2::0", score=0.34, content="Another chunk", metadata={"relative_path": "notes/note2.md"}
            ),
        ]


@pytest.mark.asyncio
async def test_semantic_search_tool_formats_results():
    indexer = StubIndexer()
    tool = create_semantic_search_tool(indexer)

    result = await tool.python_callable(query="focus", limit=2, path_filter="note1.md")

    assert "note1.md" in result
    assert "0.12" in result
    assert "Chunk text" in result
    assert indexer.calls[-1] == ("focus", 2, "note1.md")


class FakeAgent:
    def __init__(self, *, tools, handoffs, **_: object) -> None:
        self.tools = tools
        self.handoffs = handoffs


class StubMCPServer:
    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - simple stub
        self.args = args
        self.kwargs = kwargs

    async def connect(self) -> None:  # pragma: no cover - simple stub
        return None

    async def cleanup(self) -> None:  # pragma: no cover - simple stub
        return None


class FakeObsidianAgent:
    def __init__(self, *, tools, **kwargs) -> None:
        self.tools = tools
        self.kwargs = kwargs


@pytest.mark.asyncio
async def test_obsidian_agent_registers_semantic_search_tool(monkeypatch):
    from telegram_bot.ai_assistant.agents import obsidian_agent as module

    monkeypatch.setattr(module, "MCPServerStdio", StubMCPServer)
    monkeypatch.setattr(module, "Agent", FakeObsidianAgent)
    monkeypatch.setattr(module.atexit, "register", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.ModelFactory, "build_model", lambda **kwargs: "model")

    config = module.ObsidianAgentConfig()
    indexer = StubIndexer()

    agent = await module.get_obsidian_agent(config, embedding_indexer=indexer)

    semantic_tools = [
        tool for tool in agent.tools if "semantic_search" in getattr(tool, "name", getattr(tool, "__name__", ""))
    ]
    assert semantic_tools, "Obsidian agent should expose semantic_search tool"
