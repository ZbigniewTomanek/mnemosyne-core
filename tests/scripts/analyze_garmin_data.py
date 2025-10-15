#!/usr/bin/env python
"""
Example script for using the GarminDataAnalysisService.

This script demonstrates how to:
1. Initialize the service
2. Fetch and store Garmin data for a specific period
3. Query the stored data for analysis
4. Generate data summaries

Usage:
"""

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

from loguru import logger

from telegram_bot.service.garmin_connect_service import GarminConnectService
from telegram_bot.service.garmin_data_analysis_service import GarminDataAnalysisService


async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Analyze Garmin Connect data using DuckDB")
    parser.add_argument("--token_dir", type=str, default="./out/garmin_tokens", help="Directory for Garmin tokens")
    parser.add_argument("--user_id", type=int, help="Telegram user ID")
    parser.add_argument("--days", type=int, default=7, help="Number of days to process (default: 7)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD format, optional)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD format, optional)")
    parser.add_argument(
        "--output",
        type=str,
        default="garmin_analysis_output.json",
        help="Output file for query results (default: garmin_analysis_output.json)",
    )

    args = parser.parse_args()

    # Parse dates if provided
    start_date = None
    end_date = None

    if args.start:
        try:
            start_date = dt.date.fromisoformat(args.start)
        except ValueError:
            logger.error(f"Invalid start date format: {args.start}. Use YYYY-MM-DD.")
            sys.exit(1)

    if args.end:
        try:
            end_date = dt.date.fromisoformat(args.end)
        except ValueError:
            logger.error(f"Invalid end date format: {args.end}. Use YYYY-MM-DD.")
            sys.exit(1)

    # Load settings (use default paths)
    out_dir = Path("./out")
    garmin_token_dir = Path(args.token_dir)

    # Initialize services
    garmin_service = GarminConnectService(garmin_token_dir)
    data_analysis_service = GarminDataAnalysisService(garmin_service, out_dir)

    try:
        # Step 1: Fetch and store data
        logger.info(f"Fetching and storing data for user {args.user_id}")
        await data_analysis_service.fetch_and_store_period_data(
            telegram_user_id=args.user_id,
            start_date=start_date,
            end_date=end_date,
            days=args.days,
        )
        # Step 4: Query detailed data
        result = await data_analysis_service.query_data(
            telegram_user_id=args.user_id,
            start_date=start_date,
            end_date=end_date,
        )

        # Write results to file
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(result, f, default=str, indent=2)

        logger.info(f"Results written to {output_path}")

    finally:
        # Close the database connection
        data_analysis_service.close()


if __name__ == "__main__":
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    # Run the async main function
    asyncio.run(main())
