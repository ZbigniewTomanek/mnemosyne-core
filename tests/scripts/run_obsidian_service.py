"""CLI tool for manually testing ObsidianService operations."""

import asyncio
from argparse import ArgumentParser
from datetime import datetime

from telegram_bot.config import BotSettings
from telegram_bot.service_factory import ServiceFactory


async def cmd_read_file(args, service):
    """Read a file from the vault."""
    content = await service.safe_read_file(args.file_path)
    print(content)


async def cmd_write_file(args, service):
    """Write content to a file in the vault."""
    await service.safe_write_file(args.file_path, args.content)
    print(f"Written to {args.file_path}")


async def cmd_append_file(args, service):
    """Append content to a file in the vault."""
    await service.safe_append_file(args.file_path, args.content)
    print(f"Appended to {args.file_path}")


async def cmd_get_daily_note_path(args, service):
    """Get the path to a daily note."""
    path = service.get_daily_note_path(args.date)
    print(f"Path: {path}")
    print(f"Exists: {path.exists()}")


async def cmd_read_daily_note(args, service):
    """Read a specific daily note."""
    path = service.get_daily_note_path(args.date)
    if not path.exists():
        print(f"Daily note for {args.date} does not exist at {path}")
        return
    content = await service.safe_read_file(path)
    print(content)


async def cmd_recent_daily_notes(args, service):
    """Get recent daily notes."""
    notes = await service.get_recent_daily_notes(args.days)
    print(f"Found {len(notes)} daily notes:\n")
    for date_str, content in notes.items():
        print(f"=== {date_str} ===")
        print(content[:200] + "..." if len(content) > 200 else content)
        print()


async def cmd_daily_notes_range(args, service):
    """Get daily notes between two dates."""
    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    notes = await service.get_daily_notes_between(start, end, max_notes=args.max_notes)
    print(f"Found {len(notes)} daily notes:\n")
    for date_str, content in notes.items():
        print(f"=== {date_str} ===")
        print(content[:200] + "..." if len(content) > 200 else content)
        print()


async def cmd_recent_ai_logs(args, service):
    """Get recent AI logs."""
    logs = await service.get_recent_ai_logs(args.days)
    print(f"Found {len(logs)} AI logs:\n")
    for date_str, content in logs.items():
        print(f"=== {date_str} ===")
        print(content[:200] + "..." if len(content) > 200 else content)
        print()


async def cmd_add_ai_log(args, service):
    """Add an entry to the AI log."""
    await service.add_ai_log_entry(args.date, args.content, entry_type=args.entry_type)
    print(f"Added {args.entry_type} entry to AI log for {args.date}")


async def cmd_persistent_memory(args, service):
    """Read persistent memory content."""
    content = await service.get_persistent_memory_content()
    if content:
        print(content)
    else:
        print("No persistent memory found or file is empty")


async def main() -> None:
    parser = ArgumentParser(description="CLI tool for testing ObsidianService operations")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Read file command
    parser_read = subparsers.add_parser("read", help="Read a file from the vault")
    parser_read.add_argument("file_path", type=str, help="Path to the file (relative to vault root)")

    # Write file command
    parser_write = subparsers.add_parser("write", help="Write content to a file")
    parser_write.add_argument("file_path", type=str, help="Path to the file (relative to vault root)")
    parser_write.add_argument("content", type=str, help="Content to write")

    # Append file command
    parser_append = subparsers.add_parser("append", help="Append content to a file")
    parser_append.add_argument("file_path", type=str, help="Path to the file (relative to vault root)")
    parser_append.add_argument("content", type=str, help="Content to append")

    # Get daily note path command
    parser_path = subparsers.add_parser("daily-path", help="Get the path to a daily note")
    parser_path.add_argument("date", type=str, help="Date in YYYY-MM-DD format")

    # Read daily note command
    parser_daily = subparsers.add_parser("read-daily", help="Read a specific daily note")
    parser_daily.add_argument("date", type=str, help="Date in YYYY-MM-DD format")

    # Recent daily notes command
    parser_recent = subparsers.add_parser("recent-daily", help="Get recent daily notes")
    parser_recent.add_argument("days", type=int, help="Number of recent days to retrieve")

    # Daily notes range command
    parser_range = subparsers.add_parser("daily-range", help="Get daily notes between two dates")
    parser_range.add_argument("start_date", type=str, help="Start date in YYYY-MM-DD format")
    parser_range.add_argument("end_date", type=str, help="End date in YYYY-MM-DD format")
    parser_range.add_argument("--max-notes", type=int, default=None, help="Maximum number of notes to retrieve")

    # Recent AI logs command
    parser_ai_recent = subparsers.add_parser("recent-ai-logs", help="Get recent AI logs")
    parser_ai_recent.add_argument("days", type=int, help="Number of recent days to retrieve")

    # Add AI log entry command
    parser_ai_add = subparsers.add_parser("add-ai-log", help="Add an entry to the AI log")
    parser_ai_add.add_argument("date", type=str, help="Date in YYYY-MM-DD format")
    parser_ai_add.add_argument("content", type=str, help="Content to add")
    parser_ai_add.add_argument("--entry-type", default="test", help="Entry type (default: test)")

    # Persistent memory command
    subparsers.add_parser("persistent-memory", help="Read persistent memory content")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    bot_settings = BotSettings()
    service_factory = ServiceFactory(bot_settings)
    obsidian_service = service_factory.obsidian_service

    # Map commands to handlers
    commands = {
        "read": cmd_read_file,
        "write": cmd_write_file,
        "append": cmd_append_file,
        "daily-path": cmd_get_daily_note_path,
        "read-daily": cmd_read_daily_note,
        "recent-daily": cmd_recent_daily_notes,
        "daily-range": cmd_daily_notes_range,
        "recent-ai-logs": cmd_recent_ai_logs,
        "add-ai-log": cmd_add_ai_log,
        "persistent-memory": cmd_persistent_memory,
    }

    handler = commands.get(args.command)
    if handler:
        await handler(args, obsidian_service)
    else:
        print(f"Unknown command: {args.command}")
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
