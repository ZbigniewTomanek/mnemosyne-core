from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from telegram_bot.service.obsidian.obsidian_service import ObsidianConfig, ObsidianService


def _setup_git_vault(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "vault"

    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True)

    subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test Bot"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "bot@example.com"], check=True)

    (repo / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitkeep"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True)

    return repo


@pytest.mark.asyncio
async def test_get_daily_notes_between_reads_current_and_archive(tmp_path):
    repo_path = _setup_git_vault(tmp_path)

    daily_dir = repo_path / "daily"
    archive_dir = daily_dir / "archive"
    archive_dir.mkdir(parents=True)

    (daily_dir / "2024-01-02.md").write_text("Note two", encoding="utf-8")
    (archive_dir / "2024-01-03.md").write_text("Note three", encoding="utf-8")

    subprocess.run(["git", "-C", str(repo_path), "add", "daily"], check=True)
    subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "seed notes"], check=True)
    subprocess.run(["git", "-C", str(repo_path), "push"], check=True)

    config = ObsidianConfig(
        obsidian_root_dir=repo_path,
        daily_notes_dir=Path("daily"),
        ai_assistant_memory_logs=Path("ai_logs"),
        persistent_memory_file="persistent_memory.md",
    )

    service = ObsidianService(config=config)

    notes = await service.get_daily_notes_between(date(2024, 1, 1), date(2024, 1, 3))

    assert list(notes.keys()) == ["2024-01-03", "2024-01-02"]
    assert notes["2024-01-03"] == "Note three"
    assert notes["2024-01-02"] == "Note two"


@pytest.mark.asyncio
async def test_get_daily_notes_between_honors_max_notes(tmp_path):
    repo_path = _setup_git_vault(tmp_path)

    daily_dir = repo_path / "daily"
    daily_dir.mkdir(parents=True)

    (daily_dir / "2024-01-01.md").write_text("Note one", encoding="utf-8")
    (daily_dir / "2024-01-02.md").write_text("Note two", encoding="utf-8")

    subprocess.run(["git", "-C", str(repo_path), "add", "daily"], check=True)
    subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "seed notes"], check=True)
    subprocess.run(["git", "-C", str(repo_path), "push"], check=True)

    config = ObsidianConfig(
        obsidian_root_dir=repo_path,
        daily_notes_dir=Path("daily"),
        ai_assistant_memory_logs=Path("ai_logs"),
        persistent_memory_file="persistent_memory.md",
    )
    service = ObsidianService(config=config)

    notes = await service.get_daily_notes_between(date(2024, 1, 1), date(2024, 1, 3), max_notes=1)

    assert list(notes.keys()) == ["2024-01-02"], "Should return the most recent note first"


@pytest.mark.asyncio
async def test_get_daily_notes_between_validates_range(tmp_path):
    repo_path = _setup_git_vault(tmp_path)

    config = ObsidianConfig(
        obsidian_root_dir=repo_path,
        daily_notes_dir="daily",
        ai_assistant_memory_logs="ai_logs",
        persistent_memory_file="persistent_memory.md",
    )
    (repo_path / "daily").mkdir(parents=True, exist_ok=True)
    (repo_path / "ai_logs").mkdir(parents=True, exist_ok=True)

    service = ObsidianService(config=config)

    with pytest.raises(ValueError):
        await service.get_daily_notes_between(date(2024, 1, 5), date(2024, 1, 1))
