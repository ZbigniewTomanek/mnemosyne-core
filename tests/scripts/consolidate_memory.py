#!/usr/bin/env python
"""
Consolidate Memory Script

This script demonstrates how to use the MemoryConsolidationTask to consolidate
AI memory and daily notes into weekly summaries and persistent facts.

Usage:
    python consolidate_memory.py --obsidian_root /path/to/obsidian/vault
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from telegram_bot import env_file_path  # noqa: F401
from telegram_bot.scheduled_tasks.memory_consolidation_task import (
    MemoryConsolidationTaskConfig,
    _perform_memory_consolidation,
)
from telegram_bot.service.obsidian.obsidian_service import ObsidianConfig, ObsidianService


def main() -> None:  # noqa: C901
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Consolidate AI memory and daily notes")
    parser.add_argument(
        "--obsidian_root",
        type=str,
        default="/Users/zbigi/projects/z-vault",
        help="Root directory of Obsidian vault",
    )
    parser.add_argument(
        "--weeks_back",
        type=int,
        default=0,
        help="Number of weeks to go back from current week (0 = previous week, 1 = two weeks ago, etc.)",
    )
    parser.add_argument(
        "--output_dir", type=str, default="./out", help="Output directory for generated files (default: ./out)"
    )
    parser.add_argument("--weekly_dir", type=str, help="Override weekly memory directory relative to vault root")
    parser.add_argument("--persistent_file", type=str, help="Override persistent memory file relative to vault root")
    parser.add_argument("--daily_notes_dir", type=str, help="Override daily notes directory relative to vault root")
    parser.add_argument("--ai_logs_dir", type=str, help="Override AI logs directory relative to vault root")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force consolidation even if files already exist",
    )
    parser.add_argument(
        "--default_section",
        type=str,
        help="Override default persistent memory section for unrouted facts",
    )
    parser.add_argument(
        "--routing_config",
        type=str,
        help="Path to JSON file containing category->section mapping for persistent memory",
    )

    args = parser.parse_args()

    # Validate obsidian root directory
    obsidian_root = Path(args.obsidian_root).expanduser().resolve()
    if not obsidian_root.exists():
        logger.error(f"Obsidian root directory does not exist: {obsidian_root}")
        sys.exit(1)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Configure memory consolidation service using exact same defaults
    memory_config = MemoryConsolidationTaskConfig()
    if args.weekly_dir:
        memory_config.weekly_memory_dir = args.weekly_dir
    if args.persistent_file:
        memory_config.persistent_memory_file = args.persistent_file
    if args.daily_notes_dir:
        memory_config.daily_notes_dir = args.daily_notes_dir
    if args.ai_logs_dir:
        memory_config.ai_logs_dir = args.ai_logs_dir
    if args.default_section:
        memory_config.persistent_memory_default_section = args.default_section
    if args.routing_config:
        routing_path = Path(args.routing_config).expanduser().resolve()
        if not routing_path.exists():
            logger.error(f"Routing config not found: {routing_path}")
            sys.exit(1)
        try:
            memory_config.persistent_memory_section_routing = json.loads(routing_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - CLI validation path
            logger.error(f"Failed to parse routing config JSON: {exc}")
            sys.exit(1)

    # Initialize obsidian service
    obsidian_config = ObsidianConfig(obsidian_root_dir=obsidian_root)
    obsidian_service = ObsidianService(config=obsidian_config)

    # Calculate which week to process
    tz = timezone(timedelta(hours=2))  # Europe/Warsaw timezone
    today = datetime.now(tz=tz).date()
    days_since_monday = today.weekday()
    target_monday = today - timedelta(days=days_since_monday + 7 + (args.weeks_back * 7))
    target_sunday = target_monday + timedelta(days=6)

    year, week_num, _ = target_monday.isocalendar()

    logger.info(f"Processing memory consolidation for week {year}-W{week_num:02d}")
    logger.info(f"Week range: {target_monday} to {target_sunday}")

    # Check if files already exist
    weekly_file_path = obsidian_service.get_weekly_memory_path(year, week_num, memory_config.weekly_memory_dir)
    persistent_file_path = obsidian_service.get_persistent_memory_path(memory_config.persistent_memory_file)

    if weekly_file_path.exists() and not args.force:
        logger.warning(f"Weekly memory file already exists: {weekly_file_path}")
        logger.info("Use --force to overwrite existing files")

        # Ask user for confirmation
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response not in ["y", "yes"]:
            logger.info("Consolidation cancelled by user")
            sys.exit(0)

    try:
        # Use the exact same implementation as the scheduled task
        logger.info("Starting memory consolidation...")

        # Serialize configs exactly like the scheduled task does
        memory_config_dict = {
            "enabled": memory_config.enabled,
            "weekly_memory_dir": memory_config.weekly_memory_dir,
            "persistent_memory_file": memory_config.persistent_memory_file,
            "ai_logs_dir": memory_config.ai_logs_dir,
            "daily_notes_dir": memory_config.daily_notes_dir,
            "summarization_llm_config": memory_config.summarization_llm_config.model_dump(),
            "fact_extraction_llm_config": memory_config.fact_extraction_llm_config.model_dump(),
            "days_to_process_for_weekly": memory_config.days_to_process_for_weekly,
            "weekly_summary_prompt": memory_config.weekly_summary_prompt,
            "fact_extraction_prompt": memory_config.fact_extraction_prompt,
            "persistent_memory_default_section": memory_config.persistent_memory_default_section,
            "persistent_memory_section_routing": memory_config.persistent_memory_section_routing,
        }

        obsidian_config_dict = {
            "obsidian_root_dir": str(obsidian_config.obsidian_root_dir),
            "daily_notes_dir": str(obsidian_config.daily_notes_dir),
            "ai_assistant_memory_logs": str(obsidian_config.ai_assistant_memory_logs),
        }

        # Call the exact same function that the scheduled task uses
        result = _perform_memory_consolidation(memory_config_dict, obsidian_config_dict)

        if result.get("status") == "success":
            logger.success("Memory consolidation completed successfully!")
            logger.info(f"Week processed: {result.get('week_processed')}")
            logger.info(f"Weekly summary saved to: {result.get('weekly_file')}")
            logger.info(
                "Persistent memory delta - add: {add}, update: {update}, remove: {remove}",
                add=result.get("facts_extracted", 0),
                update=result.get("facts_updated", 0),
                remove=result.get("facts_removed", 0),
            )
            logger.info(f"Persistent memory updated: {result.get('persistent_file')}")

            delta_summary = result.get("persistent_memory_delta", {})
            if delta_summary:
                logger.info("Section deltas:")
                for section_name, counters in delta_summary.items():
                    logger.info(
                        "  - {section}: add={add}, update={update}, remove={remove}",
                        section=section_name,
                        add=counters.get("add", 0),
                        update=counters.get("update", 0),
                        remove=counters.get("remove", 0),
                    )

            # Copy files to output directory for easy access
            if weekly_file_path.exists():
                output_weekly = output_dir / f"weekly_memory_{year}-W{week_num:02d}.md"
                output_weekly.write_text(weekly_file_path.read_text(encoding="utf-8"), encoding="utf-8")
                logger.info(f"Weekly summary copied to: {output_weekly}")

            if persistent_file_path.exists():
                output_persistent = output_dir / "persistent_memory.md"
                output_persistent.write_text(persistent_file_path.read_text(encoding="utf-8"), encoding="utf-8")
                logger.info(f"Persistent memory copied to: {output_persistent}")

        elif result.get("status") == "skipped":
            logger.warning(f"Memory consolidation skipped: {result.get('reason')}")
        else:
            logger.error(f"Memory consolidation failed: {result.get('error')}")
            sys.exit(1)

    except Exception as e:
        logger.exception(e)
        logger.error(f"Failed to consolidate memory: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Configure logging - debug logs to stdout, info+ to stderr
    logger.remove()
    logger.add(
        sys.stdout,
        level="DEBUG",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",  # noqa: E501
    )
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    )

    # Run the main function
    main()
