#!/usr/bin/env python3
"""
Export Garmin Connect data using the GarminConnectService.

This script exports Garmin data in multiple formats:
1. Raw JSON data (complete data from all endpoints)
2. Aggregated JSON (processed and summarized data)
3. Markdown report (human-readable summary)

Usage:
    python export_garmin_data.py --user_id 123456789 --token_dir ./tokens --output_dir ./output --date 2025-05-01 --days 7
"""

import argparse
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger

from telegram_bot.service.garmin_connect_service import GarminConnectService


class DateEncoder(json.JSONEncoder):
    """JSON encoder that can handle date objects."""

    def default(self, obj):
        if isinstance(obj, dt.date):
            return obj.isoformat()
        return super().default(obj)


async def export_garmin_data(
    telegram_user_id: int,
    token_store_dir: Path,
    output_dir: Path,
    date: Optional[dt.date] = None,
    days: int = 7,
):
    """
    Export Garmin Connect data in multiple formats.

    Args:
        telegram_user_id: Telegram user ID with linked Garmin account.
        token_store_dir: Directory where tokens are stored.
        output_dir: Directory to save output files.
        date: Start date for data export (optional).
        days: Number of days to export (default: 7).
    """
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Format timestamp for filenames
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Format date range for filenames
    date_str = date.isoformat() if date else dt.datetime.now().date().isoformat()
    end_date = date + dt.timedelta(days=days - 1) if date else dt.datetime.now().date() + dt.timedelta(days=days - 1)
    end_date_str = end_date.isoformat()
    date_range = f"{date_str}_to_{end_date_str}"

    # Initialize the service
    service = GarminConnectService(token_store_dir)
    logger.info(f"Exporting data for user {telegram_user_id} from {date_str} to {end_date_str}")

    # Export raw JSON data
    raw_file = output_dir / f"garmin_raw_{date_range}_{timestamp}.json"
    logger.info(f"Exporting raw data to {raw_file}")
    raw_data = await service.export_raw_json(telegram_user_id, date, end_date, days)
    if raw_data:
        with open(raw_file, "w") as f:
            json.dump(raw_data, f, cls=DateEncoder, indent=2)
        logger.info(f"Exported raw data for {len(raw_data)} days")
    else:
        logger.error("Failed to export raw data")

    # Export aggregated JSON data
    agg_file = output_dir / f"garmin_aggregated_{date_range}_{timestamp}.json"
    logger.info(f"Exporting aggregated data to {agg_file}")
    agg_data = await service.export_aggregated_json(telegram_user_id, date, end_date, days)
    if agg_data:
        with open(agg_file, "w") as f:
            json.dump(agg_data, f, cls=DateEncoder, indent=2)
        logger.info(f"Exported aggregated data with {len(agg_data.get('daily_data', []))} days")
    else:
        logger.error("Failed to export aggregated data")

    # Export markdown report
    md_file = output_dir / f"garmin_report_{date_range}_{timestamp}.md"
    logger.info(f"Exporting markdown report to {md_file}")
    md_report = await service.generate_markdown_report(telegram_user_id, date, end_date, days)
    if md_report:
        with open(md_file, "w") as f:
            f.write(md_report)
        logger.info(f"Exported markdown report with {len(md_report)} characters")
    else:
        logger.error("Failed to generate markdown report")

    logger.info(f"Export completed. Files saved to {output_dir}")
    return {
        "raw_file": raw_file if raw_data else None,
        "aggregated_file": agg_file if agg_data else None,
        "markdown_file": md_file if md_report else None,
    }


def configure_logging(log_file: Optional[str] = None, log_level: str = "INFO"):
    """Configure logging with loguru."""
    logger.remove()  # Remove default handler

    # Console logger
    logger.add(
        lambda msg: print(msg, end=""),
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # File logger if requested
    if log_file:
        logger.add(
            log_file,
            rotation="10 MB",
            compression="zip",
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        )


async def main():
    """Parse arguments and run the export function."""
    parser = argparse.ArgumentParser(description="Export Garmin Connect data using GarminConnectService")
    parser.add_argument("--user_id", type=int, required=True, help="Telegram user ID")
    parser.add_argument("--token_dir", type=str, required=True, help="Directory where tokens are stored")
    parser.add_argument("--output_dir", type=str, required=True, help="Directory to save output files")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Start date for data export (format: YYYY-MM-DD). If not provided, today's date is used.",
    )
    parser.add_argument("--days", type=int, default=7, help="Number of days to export (default: 7)")
    parser.add_argument("--log_file", type=str, help="Log to this file in addition to console")
    parser.add_argument(
        "--log_level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    configure_logging(args.log_file, args.log_level)

    # Convert string date to date object if provided
    start_date = None
    if args.date:
        try:
            start_date = dt.date.fromisoformat(args.date)
        except ValueError:
            logger.error(f"Invalid date format: {args.date}, expected YYYY-MM-DD")
            return 1

    # Export data
    token_store_dir = Path(args.token_dir)
    output_dir = Path(args.output_dir)

    try:
        result = await export_garmin_data(
            telegram_user_id=args.user_id,
            token_store_dir=token_store_dir,
            output_dir=output_dir,
            date=start_date,
            days=args.days,
        )

        # Print summary
        print("\nExport summary:")
        print(f"Raw JSON: {os.path.basename(result['raw_file']) if result['raw_file'] else 'Failed to export'}")
        print(
            f"Aggregated JSON: {os.path.basename(result['aggregated_file']) if result['aggregated_file'] else 'Failed to export'}"
        )
        print(
            f"Markdown report: {os.path.basename(result['markdown_file']) if result['markdown_file'] else 'Failed to export'}"
        )

        return 0
    except Exception as e:
        logger.exception(f"Error exporting data: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
