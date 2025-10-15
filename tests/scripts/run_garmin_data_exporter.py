#!/usr/bin/env python3
"""
Test script for GarminDataExporter service.
Exports data from docker container and prints sample data from all DataFrames.
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

from telegram_bot.service.influxdb_garmin_data_exporter import InfluxDBGarminDataExporter

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def print_dataframe_info(name: str, df):
    """Print information about a DataFrame."""
    if df is None:
        print(f"\n{name}: No data available")
        return

    print(f"\n{name}:")
    print(f"  Shape: {df.shape}")
    print(f"  Columns: {list(df.columns)}")

    if not df.empty:
        print("  Sample data (first 3 rows):")
        print(df.head(3).to_string(index=False))
    else:
        print("  DataFrame is empty")


async def main():
    """Main function to test GarminDataExporter."""
    print("Testing GarminDataExporter...")

    try:
        # Initialize exporter
        exporter = InfluxDBGarminDataExporter()

        # Export data for last 7 days
        print("Exporting Garmin data for last 7 days...")
        await exporter.refresh_influxdb_data(start_date=date.today(), end_date=None)  # Refresh data if needed
        data = await exporter.export_data(days=7)

        print("\n" + "=" * 60)
        print("GARMIN DATA EXPORT RESULTS")
        print("=" * 60)

        # Print info for each DataFrame
        print_dataframe_info("Activity GPS", data.activity_gps)
        print_dataframe_info("Activity Lap", data.activity_lap)
        print_dataframe_info("Activity Session", data.activity_session)
        print_dataframe_info("Activity Summary", data.activity_summary)
        print_dataframe_info("Body Battery Intraday", data.body_battery_intraday)
        print_dataframe_info("Breathing Rate Intraday", data.breathing_rate_intraday)
        print_dataframe_info("Daily Stats", data.daily_stats)
        print_dataframe_info("HRV Intraday", data.hrv_intraday)
        print_dataframe_info("Heart Rate Intraday", data.heart_rate_intraday)
        print_dataframe_info("Race Predictions", data.race_predictions)
        print_dataframe_info("Sleep Intraday", data.sleep_intraday)
        print_dataframe_info("Sleep Summary", data.sleep_summary)
        print_dataframe_info("Steps Intraday", data.steps_intraday)
        print_dataframe_info("Stress Intraday", data.stress_intraday)

        print("\n" + "=" * 60)
        print("Export completed successfully!")

    except Exception as e:
        print(f"Error during export: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
