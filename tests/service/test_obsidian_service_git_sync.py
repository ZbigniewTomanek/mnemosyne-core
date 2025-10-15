from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from telegram_bot.service.obsidian.obsidian_service import ObsidianConfig, ObsidianService


def _run_git(command: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *command],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_git_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    local = tmp_path / "vault"

    _run_git(["init", "--bare", str(remote)])
    _run_git(["clone", str(remote), str(local)])

    _run_git(["checkout", "-b", "main"], cwd=local)
    _run_git(["config", "user.name", "Test Bot"], cwd=local)
    _run_git(["config", "user.email", "bot@example.com"], cwd=local)

    (local / "README.md").write_text("initial", encoding="utf-8")
    _run_git(["add", "README.md"], cwd=local)
    _run_git(["commit", "-m", "initial"], cwd=local)
    _run_git(["push", "-u", "origin", "main"], cwd=local)

    return local, remote


@pytest.mark.asyncio
async def test_safe_write_file_commits_and_pushes_changes(tmp_path):
    repo_path, remote_path = _create_git_repo(tmp_path)

    config = ObsidianConfig(
        obsidian_root_dir=repo_path,
        daily_notes_dir=Path("daily"),
        ai_assistant_memory_logs=Path("ai_logs"),
        persistent_memory_file=Path("persistent_memory.md"),
        git_branch="main",
        git_remote="origin",
        auto_push=True,
        commit_message_template="telegram bot: auto sync {timestamp}",
    )

    service = ObsidianService(config=config)

    target_file = repo_path / "daily" / "2024-05-01.md"

    assert _run_git(["status", "--porcelain"], cwd=repo_path) == ""

    await service.safe_write_file(target_file, "Hello from bot\n")

    file_content = target_file.read_text(encoding="utf-8")
    assert file_content == "Hello from bot\n"

    last_commit_message = _run_git(["log", "-1", "--pretty=%s"], cwd=repo_path)
    assert last_commit_message.startswith("telegram bot: auto sync ")

    timestamp_match = re.search(r"telegram bot: auto sync (.+)", last_commit_message)
    assert timestamp_match is not None
    datetime.fromisoformat(timestamp_match.group(1))

    remote_head = _run_git(["log", "main", "-1", "--pretty=%s"], cwd=remote_path)
    assert remote_head == last_commit_message

    lock_path = repo_path / ".vault.lock"
    assert not lock_path.exists()


@pytest.mark.asyncio
async def test_safe_write_file_skips_commit_when_no_changes(tmp_path):
    repo_path, _ = _create_git_repo(tmp_path)

    config = ObsidianConfig(
        obsidian_root_dir=repo_path,
        daily_notes_dir=Path("daily"),
        ai_assistant_memory_logs=Path("ai_logs"),
        persistent_memory_file=Path("persistent_memory.md"),
        git_branch="main",
        git_remote="origin",
        auto_push=True,
        commit_message_template="telegram bot: auto sync {timestamp}",
    )

    service = ObsidianService(config=config)

    target_file = repo_path / "daily" / "2024-05-02.md"

    assert _run_git(["status", "--porcelain"], cwd=repo_path) == ""

    await service.safe_write_file(target_file, "first state")
    first_commit = _run_git(["rev-parse", "HEAD"], cwd=repo_path)

    await service.safe_write_file(target_file, "first state")
    second_commit = _run_git(["rev-parse", "HEAD"], cwd=repo_path)

    assert first_commit == second_commit


@pytest.mark.asyncio
async def test_transaction_raises_on_dirty_repo(tmp_path):
    repo_path, _ = _create_git_repo(tmp_path)

    (repo_path / "untracked.txt").write_text("dirty", encoding="utf-8")

    config = ObsidianConfig(
        obsidian_root_dir=repo_path,
        daily_notes_dir=Path("daily"),
        ai_assistant_memory_logs=Path("ai_logs"),
        persistent_memory_file=Path("persistent_memory.md"),
        git_branch="main",
        git_remote="origin",
        auto_push=True,
        commit_message_template="telegram bot: auto sync {timestamp}",
    )

    service = ObsidianService(config=config)

    with pytest.raises(RuntimeError):
        await service.safe_write_file(repo_path / "daily" / "note.md", "content")
