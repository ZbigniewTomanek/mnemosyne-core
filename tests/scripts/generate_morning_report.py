#!/usr/bin/env python
"""
Generate Morning Report Script

This script demonstrates how to use the MorningReportService to generate
a personalized morning report based on Garmin data and Obsidian notes.

Usage:
    python generate_morning_report.py --obsidian_root /path/to/obsidian/vault
"""
import argparse
import asyncio
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

from telegram_bot import env_file_path  # noqa: F401
from telegram_bot.config import BotSettings
from telegram_bot.constants import DefaultLLMConfig
from telegram_bot.service.calendar_service.calendar_service import CalendarService
from telegram_bot.service.db_service import DBService
from telegram_bot.service.influxdb_garmin_data_exporter import InfluxDBGarminDataExporter
from telegram_bot.service.morning_report_service import MorningReportConfig, MorningReportService
from telegram_bot.service.obsidian.obsidian_service import ObsidianConfig, ObsidianService


async def main():
    # Parse command line arguments
    bot_config = BotSettings()
    parser = argparse.ArgumentParser(description="Generate morning report using MorningReportService")
    parser.add_argument(
        "--obsidian_root",
        type=str,
        default="/Users/zbigi/projects/z-vault",
        help="Root directory of Obsidian vault",
    )
    parser.add_argument("--days", type=int, default=3, help="Number of days to look back (default: 3)")
    parser.add_argument(
        "--output",
        type=str,
        default="morning_report.md",
        help="Output file for the morning report (default: morning_report.md)",
    )

    args = parser.parse_args()

    # Validate obsidian root directory
    obsidian_root = Path(args.obsidian_root).resolve()
    if not obsidian_root.exists():
        logger.error(f"Obsidian root directory does not exist: {obsidian_root}")
        sys.exit(1)

    # Configure morning report service
    morning_config = MorningReportConfig(
        summarizing_llm_config=DefaultLLMConfig.GEMINI_PRO,
        number_of_days=args.days,
        garmin_container_name="garmin-fetch-data",
    )

    # Initialize obsidian service
    obsidian_config = ObsidianConfig(obsidian_root_dir=obsidian_root)
    obsidian_service = ObsidianService(config=obsidian_config)

    # Initialize the morning report service
    morning_service = MorningReportService(
        morning_report_config=morning_config,
        obsidian_service=obsidian_service,
        db_service=DBService(bot_config.out_dir),
        garmin_data_exporter=InfluxDBGarminDataExporter(),
        calendar_service=CalendarService(config=bot_config.calendar_config),
        tz=ZoneInfo("Europe/Warsaw"),
    )

    try:
        # Generate the morning report
        logger.info(f"Generating morning report for {args.days} days...")
        report = await morning_service.create_morning_summary(user_id=None)

        # Write the report to file
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        logger.success(f"Morning report generated successfully and saved to {output_path}")
        logger.info(f"Report length: {len(report)} characters")

        # Also print to console for immediate viewing
        print("\n" + "=" * 60)
        print("GENERATED MORNING REPORT")
        print("=" * 60)
        print(report)
        print("=" * 60)

    except Exception as e:
        logger.exception(e)
        logger.error(f"Failed to generate morning report: {e}")
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

    # Run the async main function
    asyncio.run(main())
