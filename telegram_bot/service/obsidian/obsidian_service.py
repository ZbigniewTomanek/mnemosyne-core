from __future__ import annotations

import asyncio
import fcntl
import os
import re
import tempfile
import time
from asyncio import subprocess as aio_subprocess
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Optional, Union
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic import BaseModel


@asynccontextmanager
async def file_lock(lock_file_path: Path, lock_type: int = fcntl.LOCK_EX, timeout: int = 30) -> AsyncIterator[None]:
    """An async context manager for an advisory file lock.

    Args:
        lock_file_path: Path to the lock file
        lock_type: Type of lock (fcntl.LOCK_EX or fcntl.LOCK_SH)
        timeout: Maximum time to wait for lock acquisition

    Raises:
        TimeoutError: If unable to acquire lock within timeout
    """
    lock_file = None
    start_time = time.time()

    try:
        # Open the lock file in a way that works with iCloud
        lock_file = open(lock_file_path, "w")

        # Non-blocking loop to wait for the lock
        while True:
            try:
                fcntl.flock(lock_file, lock_type | fcntl.LOCK_NB)
                break  # Lock acquired successfully
            except (IOError, BlockingIOError):
                # Check for timeout
                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Failed to acquire lock on {lock_file_path.name} within {timeout} seconds")

                logger.debug(f"File related to {lock_file_path.name} is locked, waiting...")
                await asyncio.sleep(0.1)  # Wait 100ms before retrying

        yield

    finally:
        if lock_file:
            # Release the lock and close the file
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
                lock_file.close()
                # Clean up the .lock file
                lock_file_path.unlink()
            except OSError:
                pass  # May already be gone


class ObsidianConfig(BaseModel):
    """Configuration for Obsidian vault and directory structure."""

    obsidian_root_dir: Path = Path("/Users/zbigi/projects/z-vault")
    daily_notes_dir: Path = Path("01 management/10 process/0 daily")
    ai_assistant_memory_logs: Path = Path("30 AI Assistant/memory/logs")
    persistent_memory_file: Path = Path("30 AI Assistant/memory/persistent_memory.md")
    git_branch: str = "main"
    git_remote: str = "origin"
    auto_push: bool = True
    commit_message_template: str = "telegram bot: auto sync {timestamp}"
    vault_lock_filename: str = ".vault.lock"
    push_retry_attempts: int = 3
    read_cache_ttl: int = 30  # seconds, 0 = always sync, -1 = no caching
    force_sync_on_write: bool = True
    check_remote_ref_first: bool = True


class GitCommandError(RuntimeError):
    """Represents a failure when executing a git command."""

    def __init__(self, command: tuple[str, ...], returncode: int, stdout: str, stderr: str) -> None:
        message = "Git command failed: {} (exit code {})".format(" ".join(command), returncode)
        if stderr:
            message = f"{message}: {stderr}"
        elif stdout:
            message = f"{message}: {stdout}"

        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@dataclass
class _GitSyncState:
    """Tracks git sync cache state for TTL-based optimization."""

    last_fetch_time: datetime | None = None
    last_pull_time: datetime | None = None
    last_known_remote_sha: str | None = None
    last_local_sha: str | None = None


@dataclass
class _VaultTransactionState:
    """Tracks state for an in-flight vault transaction."""

    read_only: bool
    lock_file: IO[str]
    lock_path: Path
    modified_paths: set[Path] = field(default_factory=set)

    def mark_modified(self, path: Path) -> None:
        self.modified_paths.add(path)


class ObsidianService:
    """Service for handling Obsidian vault file operations."""

    def __init__(self, config: ObsidianConfig, tz: ZoneInfo | None = None) -> None:
        """Initialize the Obsidian service with configuration.

        Args:
            config: ObsidianConfig containing vault paths and directory structure
        """
        self.config = config
        self.tz = tz or ZoneInfo("Europe/Warsaw")

        # Intra-process lock dictionary to prevent concurrent access to same file path
        self._path_locks: defaultdict[Path, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Ensure root directory exists and is a git repository
        if not self.config.obsidian_root_dir.exists():
            raise FileNotFoundError(f"Obsidian root directory not found: {self.config.obsidian_root_dir}")

        git_dir = self.config.obsidian_root_dir / ".git"
        if not git_dir.exists():
            raise FileNotFoundError(
                f"Obsidian vault must be a git repository, missing .git directory at: {self.config.obsidian_root_dir}"
            )

        self._vault_async_lock = asyncio.Lock()
        self._transaction_context: ContextVar[_VaultTransactionState | None] = ContextVar(
            f"obsidian_vault_transaction_{id(self)}", default=None
        )
        self._root_dir = self.config.obsidian_root_dir.resolve()
        self._sync_state = _GitSyncState()

    def _resolve_vault_path(self, file_path: Union[str, Path]) -> Path:
        """Resolve a path to an absolute path within the vault."""

        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = self._root_dir / candidate

        candidate = candidate.resolve(strict=False)
        if not candidate.is_relative_to(self._root_dir):
            raise ValueError(f"Path {candidate} is outside of the Obsidian vault")
        return candidate

    def _relative_to_root(self, path: Path) -> Path:
        """Return path relative to vault root."""

        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self._root_dir):
            raise ValueError(f"Path {resolved} is outside of the Obsidian vault")
        return resolved.relative_to(self._root_dir)

    async def _run_git_command(self, *args: str, check: bool = True) -> tuple[str, str]:
        """Execute a git command asynchronously within the vault directory."""

        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(self._root_dir),
            stdout=aio_subprocess.PIPE,
            stderr=aio_subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if process.returncode != 0 and check:
            raise GitCommandError(tuple(args), process.returncode or -1, stdout, stderr)

        return stdout, stderr

    async def _get_remote_ref(self) -> str:
        """Lightweight check of remote HEAD SHA without fetching."""
        try:
            stdout, _ = await self._run_git_command(
                "ls-remote", self.config.git_remote, f"refs/heads/{self.config.git_branch}"
            )
            # Returns: "<sha>\trefs/heads/main"
            return stdout.split()[0] if stdout else ""
        except Exception as exc:
            logger.warning(f"Failed to get remote ref: {exc}")
            return ""

    async def _should_sync(self, is_write: bool) -> bool:
        """Determine if we need to fetch/pull based on cache state and operation type."""

        # Always sync for writes (safety)
        if is_write and self.config.force_sync_on_write:
            return True

        # No cache for reads if TTL is -1
        if not is_write and self.config.read_cache_ttl < 0:
            return True

        # Never cache if TTL is 0
        if self.config.read_cache_ttl == 0:
            return True

        # Check if cache is fresh
        if self._sync_state.last_fetch_time:
            elapsed = (datetime.now(timezone.utc) - self._sync_state.last_fetch_time).total_seconds()
            if elapsed < self.config.read_cache_ttl:
                logger.debug(f"Using cached git state (age: {elapsed:.1f}s)")
                return False

        # Check if remote changed (lightweight)
        if self.config.check_remote_ref_first:
            remote_sha = await self._get_remote_ref()
            if remote_sha and remote_sha == self._sync_state.last_known_remote_sha:
                logger.debug("Remote unchanged, skipping fetch/pull")
                # Update cache timestamp since we verified remote hasn't changed
                self._sync_state.last_fetch_time = datetime.now(timezone.utc)
                return False

        return True

    async def _ensure_clean_worktree(self) -> None:
        """Raise if there are uncommitted changes in the worktree."""

        status, _ = await self._run_git_command("status", "--porcelain")
        relevant_lines = []
        for line in status.splitlines():
            if not line.strip():
                continue
            # Git status format: "XY filename" where XY are status codes (2 chars)
            filename = line[3:].strip() if len(line) > 3 else line
            if filename != self.config.vault_lock_filename:
                relevant_lines.append(line)

        if relevant_lines:
            logger.debug(
                "Git status before transaction not clean (filtered .vault.lock):\n{}",
                "\n".join(relevant_lines),
            )
            raise RuntimeError("Obsidian vault has uncommitted changes; cannot start a transactional operation.")

    async def _git_fetch(self) -> None:
        await self._run_git_command("fetch", self.config.git_remote)

    async def _git_pull(self) -> None:
        try:
            await self._run_git_command(
                "pull",
                "--rebase",
                self.config.git_remote,
                self.config.git_branch,
            )
        except GitCommandError as exc:
            logger.error("Git pull --rebase failed: {}", exc)
            try:
                await self._run_git_command("rebase", "--abort", check=False)
                logger.info("Successfully aborted failed rebase")
            except Exception as abort_exc:
                logger.error("Failed to abort rebase - manual intervention may be required: {}", abort_exc)
            raise exc

    async def _git_push(self) -> None:
        await self._run_git_command("push", self.config.git_remote, self.config.git_branch)

    async def _git_push_with_retry(self) -> None:
        """Push with exponential backoff retry."""
        for attempt in range(self.config.push_retry_attempts):
            try:
                await self._git_push()
                logger.debug("Pushed Obsidian vault changes to remote")
                return
            except GitCommandError as exc:
                if attempt < self.config.push_retry_attempts - 1:
                    wait_time = 2**attempt  # 1s, 2s, 4s
                    logger.warning(
                        f"Push failed (attempt {attempt + 1}/{self.config.push_retry_attempts}), "
                        f"retrying in {wait_time}s: {exc}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "Push failed after {} attempts. Commit exists locally but not on remote. "
                        "Will retry on next sync: {}",
                        self.config.push_retry_attempts,
                        exc,
                    )
                    # Don't raise - commit is safe locally
                    return

    async def _git_add_paths(self, paths: Iterable[Path]) -> None:
        unique_paths = {self._relative_to_root(path) for path in paths}
        if not unique_paths:
            return

        args = ["add", "--"]
        args.extend(str(path) for path in sorted(unique_paths))
        await self._run_git_command(*args)

    async def _has_pending_changes(self) -> bool:
        status, _ = await self._run_git_command("status", "--porcelain")
        for line in status.splitlines():
            if not line.strip():
                continue
            # Git status format: "XY filename" where XY are status codes (2 chars)
            filename = line[3:].strip() if len(line) > 3 else line
            if filename != self.config.vault_lock_filename:
                return True
        return False

    def _render_commit_message(self) -> str:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return self.config.commit_message_template.format(timestamp=timestamp)

    async def _release_vault_lock(self, state: _VaultTransactionState) -> None:
        try:
            await asyncio.to_thread(fcntl.flock, state.lock_file, fcntl.LOCK_UN)
        finally:
            state.lock_file.close()
            try:
                state.lock_path.unlink()
            except FileNotFoundError:
                pass

    async def _finalize_transaction(self, state: _VaultTransactionState) -> None:
        if not state.modified_paths:
            logger.debug("Vault transaction completed without file changes")
            return

        await self._git_add_paths(state.modified_paths)

        if not await self._has_pending_changes():
            logger.debug("No staged changes detected after write; skipping commit")
            return

        commit_message = self._render_commit_message()

        try:
            await self._run_git_command("commit", "-m", commit_message)
            logger.debug("Committed changes to Obsidian vault: {}", commit_message)
        except GitCommandError as exc:
            if "nothing to commit" in exc.stderr.lower():
                logger.debug("Git reported nothing to commit; skipping")
            else:
                raise
        else:
            if self.config.auto_push:
                await self._git_push_with_retry()

    @asynccontextmanager
    async def _vault_transaction(self, *, read_only: bool) -> AsyncIterator[_VaultTransactionState]:
        existing_state = self._transaction_context.get()
        if existing_state is not None:
            if not read_only and existing_state.read_only:
                raise RuntimeError("Cannot start a write transaction inside a read-only transaction")
            yield existing_state
            return

        await self._vault_async_lock.acquire()
        lock_path = self._root_dir / self.config.vault_lock_filename
        lock_file = open(lock_path, "w", encoding="utf-8")

        try:
            await asyncio.to_thread(fcntl.flock, lock_file, fcntl.LOCK_EX)
        except Exception:
            lock_file.close()
            self._vault_async_lock.release()
            raise

        state = _VaultTransactionState(read_only=read_only, lock_file=lock_file, lock_path=lock_path)
        token = self._transaction_context.set(state)

        try:
            await self._ensure_clean_worktree()

            # Smart sync based on cache state and operation type
            if await self._should_sync(is_write=not read_only):
                await self._git_fetch()
                await self._git_pull()

                # Update cache state
                self._sync_state.last_fetch_time = datetime.now(timezone.utc)
                self._sync_state.last_pull_time = datetime.now(timezone.utc)
                self._sync_state.last_known_remote_sha = await self._get_remote_ref()
                local_sha, _ = await self._run_git_command("rev-parse", "HEAD")
                self._sync_state.last_local_sha = local_sha

            yield state

            if not read_only:
                await self._finalize_transaction(state)
        finally:
            self._transaction_context.reset(token)
            await self._release_vault_lock(state)
            self._vault_async_lock.release()

    def get_daily_note_path(self, day: Union[str, date, datetime]) -> Path:
        """Get the path for a daily note file for the given day.

        Args:
            day: The date for which to get the daily note path.
                 Can be a string in 'YYYY-MM-DD' format, date object, or datetime object.

        Returns:
            Path: The full path to the daily note file (YYYY-MM-DD.md)

        Raises:
            ValueError: If the day parameter is in an invalid format
        """
        date_str = self._normalize_date_string(day)
        daily_notes_full_path = self.config.obsidian_root_dir / self.config.daily_notes_dir
        archive_path = daily_notes_full_path / "archive" / f"{date_str}.md"
        if archive_path.exists():
            return archive_path
        non_archive_path = daily_notes_full_path / f"{date_str}.md"
        return non_archive_path

    def get_ai_log_path(self, day: Union[str, date, datetime]) -> Path:
        """Get the path for an AI log file for the given day.

        Args:
            day: The date for which to get the AI log path.
                 Can be a string in 'YYYY-MM-DD' format, date object, or datetime object.

        Returns:
            Path: The full path to the AI log file (YYYY-MM-DD_ai_log.md)

        Raises:
            ValueError: If the day parameter is in an invalid format
        """
        date_str = self._normalize_date_string(day)
        ai_logs_full_path = self.config.obsidian_root_dir / self.config.ai_assistant_memory_logs
        return ai_logs_full_path / f"{date_str}_ai_log.md"

    @staticmethod
    def _normalize_date_string(day: Union[str, date, datetime]) -> str:
        """Convert various date formats to YYYY-MM-DD string format.

        Args:
            day: Date in various formats

        Returns:
            str: Date in YYYY-MM-DD format

        Raises:
            ValueError: If the date format is invalid or unsupported
        """
        if isinstance(day, str):
            # Validate string format
            if len(day) == 10 and day[4] == "-" and day[7] == "-":
                try:
                    # Try to parse to validate it's a real date
                    datetime.strptime(day, "%Y-%m-%d")
                    return day
                except ValueError as e:
                    raise ValueError(f"Invalid date string format: {day}") from e
            else:
                raise ValueError(f"Date string must be in YYYY-MM-DD format, got: {day}")

        elif isinstance(day, datetime):
            return day.strftime("%Y-%m-%d")

        elif isinstance(day, date):
            return day.strftime("%Y-%m-%d")

        else:
            raise ValueError(f"Unsupported date type: {type(day)}. Use str, date, or datetime.")

    def daily_note_exists(self, day: Union[str, date, datetime]) -> bool:
        """Check if a daily note exists for the given day.

        Args:
            day: The date to check

        Returns:
            bool: True if the daily note file exists, False otherwise
        """
        return self.get_daily_note_path(day).exists()

    def ai_log_exists(self, day: Union[str, date, datetime]) -> bool:
        """Check if an AI log exists for the given day.

        Args:
            day: The date to check

        Returns:
            bool: True if the AI log file exists, False otherwise
        """
        return self.get_ai_log_path(day).exists()

    def ensure_daily_notes_dir(self) -> Path:
        """Ensure the daily notes directory exists, create if it doesn't.

        Returns:
            Path: The daily notes directory path
        """
        daily_notes_path = self.config.obsidian_root_dir / self.config.daily_notes_dir
        daily_notes_path.mkdir(parents=True, exist_ok=True)
        return daily_notes_path

    def ensure_ai_logs_dir(self) -> Path:
        """Ensure the AI logs directory exists, create if it doesn't.

        Returns:
            Path: The AI logs directory path
        """
        ai_logs_path = self.config.obsidian_root_dir / self.config.ai_assistant_memory_logs
        ai_logs_path.mkdir(parents=True, exist_ok=True)
        return ai_logs_path

    async def safe_read_file(self, file_path: Union[str, Path], encoding: str = "utf-8") -> str:
        """Read a file using process and filesystem locks within a git transaction.

        Args:
            file_path: Path to the file to read
            encoding: File encoding (default: utf-8)

        Returns:
            File content as string

        Raises:
            OSError: If file cannot be read
            FileNotFoundError: If file does not exist
        """
        path = self._resolve_vault_path(file_path)
        lock_path = path.with_suffix(path.suffix + ".lock")

        process_lock = self._path_locks[path]
        async with process_lock:
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            async with self._vault_transaction(read_only=True):
                try:
                    async with file_lock(lock_path, fcntl.LOCK_SH):
                        with open(path, "r", encoding=encoding) as file_handle:
                            return file_handle.read()
                except Exception as exc:
                    logger.error(f"Failed to read file {path}: {exc}")
                    raise

    async def safe_write_file(self, file_path: Union[str, Path], content: str, encoding: str = "utf-8") -> None:
        """Write content to a file atomically inside a git-backed transaction.

        Args:
            file_path: Path to the file to write
            content: Content to write to the file
            encoding: File encoding (default: utf-8)

        Raises:
            OSError: If file cannot be written
        """
        path = self._resolve_vault_path(file_path)
        lock_path = path.with_suffix(path.suffix + ".lock")

        process_lock = self._path_locks[path]
        async with process_lock:
            async with self._vault_transaction(read_only=False) as state:
                path.parent.mkdir(parents=True, exist_ok=True)

                async with file_lock(lock_path, fcntl.LOCK_EX):
                    temp_fd, temp_path_str = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}_", suffix=".tmp")
                    temp_path = Path(temp_path_str)
                    try:
                        with os.fdopen(temp_fd, "w", encoding=encoding) as temp_file:
                            temp_file.write(content)
                            temp_file.flush()
                            os.fsync(temp_file.fileno())

                        os.replace(temp_path, path)
                    except Exception as exc:
                        logger.error(f"Failed during atomic write for {path}: {exc}")
                        if temp_path.exists():
                            temp_path.unlink()
                        raise

                state.mark_modified(path)

    async def safe_append_file(self, file_path: Union[str, Path], content: str, encoding: str = "utf-8") -> None:
        """Append content to a file atomically using two-level locking and read-modify-replace pattern.

        Args:
            file_path: Path to the file to append to
            content: Content to append to the file
            encoding: File encoding (default: utf-8)

        Raises:
            OSError: If file cannot be written
        """
        path = self._resolve_vault_path(file_path)
        lock_path = path.with_suffix(path.suffix + ".lock")

        process_lock = self._path_locks[path]
        async with process_lock:
            async with self._vault_transaction(read_only=False) as state:
                path.parent.mkdir(parents=True, exist_ok=True)

                async with file_lock(lock_path, fcntl.LOCK_EX):
                    existing_content = ""
                    if path.exists():
                        try:
                            with open(path, "r", encoding=encoding) as current_file:
                                existing_content = current_file.read()
                        except Exception as exc:
                            logger.warning(
                                "Could not read existing file {} for append, will overwrite. Error: {}",
                                path,
                                exc,
                            )

                    new_content = existing_content + content

                    try:
                        temp_fd, temp_path_str = tempfile.mkstemp(
                            dir=path.parent, prefix=f".{path.name}_", suffix=".tmp"
                        )
                        temp_path = Path(temp_path_str)
                        with os.fdopen(temp_fd, "w", encoding=encoding) as temp_file:
                            temp_file.write(new_content)
                            temp_file.flush()
                            os.fsync(temp_file.fileno())
                        os.replace(temp_path, path)
                    except Exception as exc:
                        logger.error(f"Failed during atomic append for {path}: {exc}")
                        if "temp_path" in locals() and temp_path.exists():
                            temp_path.unlink()
                        raise

                state.mark_modified(path)

    async def get_recent_daily_notes(self, number_of_days: int) -> dict[str, str]:
        """Get recent daily notes grouped by date.

        Args:
            number_of_days: Number of recent days to retrieve

        Returns:
            dict: Dictionary mapping date strings (YYYY-MM-DD) to note content

        Raises:
            FileNotFoundError: If daily notes directory doesn't exist
        """
        daily_dir = self.config.obsidian_root_dir / self.config.daily_notes_dir
        if not daily_dir.exists():
            raise FileNotFoundError(f"Daily notes dir {daily_dir} not found")

        # Get all markdown files sorted by modification time (most recent first)
        files = sorted(daily_dir.glob("*.md"), key=lambda file_path: file_path.stat().st_mtime, reverse=True)
        files = files[:number_of_days]

        notes_by_date = {}
        for note_file_path in files:
            # Extract date from filename (assuming format like "2025-05-01.md")
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", note_file_path.name)
            if date_match:
                date_str = date_match.group(1)
                try:
                    content = await self.safe_read_file(note_file_path)
                    notes_by_date[date_str] = content
                except Exception as e:
                    logger.warning(f"Failed to read daily note {note_file_path}: {e}")
                    continue
            else:
                file_date = datetime.fromtimestamp(note_file_path.stat().st_mtime, tz=self.tz)
                date_str = file_date.strftime("%Y-%m-%d")
                try:
                    content = await self.safe_read_file(note_file_path)
                    notes_by_date[date_str] = content
                except Exception as e:
                    logger.warning(f"Failed to read daily note {note_file_path}: {e}")
                    continue

        logger.debug(f"Loaded {len(notes_by_date)} daily notes")
        return notes_by_date

    async def get_recent_ai_logs(self, number_of_days: int) -> dict[str, str]:
        """Get recent AI assistant logs grouped by date.

        Args:
            number_of_days: Number of recent days to retrieve (used for filtering files)

        Returns:
            dict: Dictionary mapping date strings (YYYY-MM-DD) to log content

        Raises:
            FileNotFoundError: If AI logs directory doesn't exist
        """
        logs_dir = self.config.obsidian_root_dir / self.config.ai_assistant_memory_logs
        if not logs_dir.exists():
            raise FileNotFoundError(f"AI memory logs dir {logs_dir} not found")

        # Get all AI log files sorted by modification time (most recent first)
        files = sorted(logs_dir.glob("*_ai_log.md"), key=lambda file_path: file_path.stat().st_mtime, reverse=True)
        files = files[:number_of_days]

        logs_by_date: dict[str, str] = {}
        for log_file_path in files:
            # Extract date from filename (assuming format like "2025-05-01_ai_log.md")
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", log_file_path.name)
            if date_match:
                date_str = date_match.group(1)
                try:
                    content = await self.safe_read_file(log_file_path)
                    if date_str in logs_by_date:
                        # If multiple logs for same date, concatenate them
                        logs_by_date[date_str] += "\n\n" + content
                    else:
                        logs_by_date[date_str] = content
                except Exception as e:
                    logger.warning(f"Failed to read AI log {log_file_path}: {e}")
                    continue
            else:
                # Fallback: use file modification time
                file_date = datetime.fromtimestamp(log_file_path.stat().st_mtime, tz=self.tz)
                date_str = file_date.strftime("%Y-%m-%d")
                try:
                    content = await self.safe_read_file(log_file_path)
                    if date_str in logs_by_date:
                        logs_by_date[date_str] += "\n\n" + content
                    else:
                        logs_by_date[date_str] = content
                except Exception as e:
                    logger.warning(f"Failed to read AI log {log_file_path}: {e}")
                    continue

        logger.debug(f"Loaded {len(files)} AI-log files")
        return logs_by_date

    async def add_ai_log_entry(
        self, day: Union[str, date, datetime], content: str, entry_type: str = "morning_report"
    ) -> None:
        """Add an entry to the AI log for a specific day.

        Args:
            day: The date for which to add the log entry.
                 Can be a string in 'YYYY-MM-DD' format, date object, or datetime object.
            content: The content to add to the AI log
            entry_type: Type of entry for formatting (e.g., "morning_report", "conversation")

        Raises:
            OSError: If the file cannot be written
        """
        ai_log_path = self.get_ai_log_path(day)

        # Format the entry with timestamp and type
        now = datetime.now(self.tz)
        timestamp = now.strftime("%H:%M:%S")

        formatted_entry = f"\n## {entry_type.title()} - {timestamp}\n\n{content}\n\n---\n"

        # Create directory if it doesn't exist
        ai_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if file exists, if not create with header + initial entry in single operation
        if not ai_log_path.exists():
            date_str = self._normalize_date_string(day)
            header = f"# AI Assistant Log - {date_str}\n\n"
            combined_content = header + formatted_entry
            await self.safe_write_file(ai_log_path, combined_content)
        else:
            # File exists, just append the new entry
            await self.safe_append_file(ai_log_path, formatted_entry)

        logger.debug(f"Added {entry_type} entry to AI log: {ai_log_path}")

    def get_weekly_memory_path(self, year: int, week_number: int, weekly_memory_dir_relative: str) -> Path:
        """Generate the path to the YYYY-Www_memory.md file within the weekly memory directory.

        Args:
            year: Year number
            week_number: ISO week number
            weekly_memory_dir_relative: Relative path to the weekly memory directory from obsidian root

        Returns:
            Path: Full path to the weekly memory file
        """
        weekly_memory_full_path = self.config.obsidian_root_dir / weekly_memory_dir_relative
        weekly_memory_full_path.mkdir(parents=True, exist_ok=True)
        return weekly_memory_full_path / f"{year}-W{week_number:02d}_memory.md"

    def get_persistent_memory_path(self, persistent_memory_file_relative: str | None = None) -> Path:
        """Generate the path to persistent_memory.md based on relative path from obsidian root.

        Args:
            persistent_memory_file_relative: Relative path to persistent memory file from obsidian root.
                                           If None, uses the path from config.

        Returns:
            Path: Full path to the persistent memory file
        """
        if persistent_memory_file_relative is None:
            persistent_memory_file_relative = str(self.config.persistent_memory_file)

        persistent_path = self.config.obsidian_root_dir / persistent_memory_file_relative
        # Ensure parent directory exists
        persistent_path.parent.mkdir(parents=True, exist_ok=True)
        return persistent_path

    async def get_persistent_memory_content(self) -> str:
        """Get persistent memory content for context in reports.

        Returns:
            str: Content of the persistent memory file, or empty string if not available
        """
        persistent_file_path = self.get_persistent_memory_path()

        if not persistent_file_path.exists():
            logger.debug("No persistent memory file found")
            return ""

        try:
            content = await self.safe_read_file(persistent_file_path)
            logger.debug("Loaded persistent memory content")
            return content
        except Exception as e:
            logger.warning(f"Failed to read persistent memory: {e}")
            return ""

    async def get_daily_notes_between(
        self,
        start_date: date,
        end_date: date,
        max_notes: int | None = None,
    ) -> dict[str, str]:
        """Return daily note contents between the provided dates (inclusive).

        Notes are returned in descending order (newest first). Missing notes are skipped
        without raising.
        """

        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        remaining = max_notes if max_notes is None or max_notes >= 0 else 0
        results: dict[str, str] = {}

        current = end_date
        while current >= start_date:
            if remaining is not None and remaining == 0:
                break

            date_str = current.isoformat()
            try:
                note_path = self.get_daily_note_path(current)
            except ValueError as exc:  # Defensive: invalid date input
                logger.warning("Invalid date provided for daily note lookup: {}", exc)
                current -= timedelta(days=1)
                continue

            if not note_path.exists():
                current -= timedelta(days=1)
                continue

            try:
                content = await self.safe_read_file(note_path)
            except FileNotFoundError:
                logger.debug("Daily note not found at {}", note_path)
                current -= timedelta(days=1)
                continue
            except Exception as exc:
                logger.warning("Failed to read daily note {}: {}", date_str, exc)
                current -= timedelta(days=1)
                continue

            results[date_str] = content
            if remaining is not None:
                remaining -= 1

            current -= timedelta(days=1)

        return results

    def generate_obsidian_link(self, note_name_or_path: str, display_text: Optional[str] = None) -> str:
        """Create an Obsidian link string.

        Args:
            note_name_or_path: The note name or path (without .md extension for link)
            display_text: Optional display text for the link

        Returns:
            str: Obsidian-formatted link
        """
        # Remove .md extension if present for the link
        link_name = note_name_or_path
        if link_name.endswith(".md"):
            link_name = link_name[:-3]

        if display_text:
            return f"[[{link_name}|{display_text}]]"
        else:
            return f"[[{link_name}]]"
