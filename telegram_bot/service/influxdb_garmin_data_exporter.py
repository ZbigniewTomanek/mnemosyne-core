import asyncio
import fcntl
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NamedTuple, Optional, Protocol

import pandas as pd
from loguru import logger


class CommandResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class AsyncCommandRunner(Protocol):
    async def run(self, cmd: list[str], cwd: Path | str | None = None) -> CommandResult:
        ...


class SubprocessRunner:
    async def run(self, cmd: list[str], cwd: Path | str | None = None) -> CommandResult:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        out = stdout_b.decode() if isinstance(stdout_b, (bytes, bytearray)) else (stdout_b or "")
        err = stderr_b.decode() if isinstance(stderr_b, (bytes, bytearray)) else (stderr_b or "")
        return CommandResult(proc.returncode, out, err)


class AsyncFileLock:
    """Simple async file-based mutex using fcntl."""

    def __init__(self, path: Path, timeout_s: float = 900.0):
        self._path = path
        self._timeout_s = timeout_s
        self._fd = None

    async def __aenter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open(self._path, "a+")
        loop = asyncio.get_event_loop()
        start = loop.time()
        attempt = 0
        while True:
            attempt += 1
            try:
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.debug(f"Acquired garmin-fetch lock on {self._path} (attempt {attempt})")
                break
            except BlockingIOError:
                waited = loop.time() - start
                if waited > self._timeout_s:
                    self._fd.close()
                    self._fd = None
                    raise TimeoutError(
                        f"Timed out waiting {int(self._timeout_s)}s for garmin-fetch lock at {self._path}"
                    )
                if attempt == 1 or attempt % 30 == 0:
                    logger.info("Another job is updating Influx; waiting… (waited {:.0f}s)", waited)
                await asyncio.sleep(1.0)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if self._fd:
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
        finally:
            if self._fd:
                self._fd.close()
                self._fd = None


@dataclass
class GarminExportData:
    """Dataclass containing exported Garmin data as pandas DataFrames.

    All DataFrames include 'measurement', 'time', 'Database_Name', and 'Device' columns.
    Time values are in ISO 8601 UTC format. DataFrames may be None if no data is available.

    Attributes:
        activity_gps: GPS coordinates and metrics during activities.
            Additional columns: latitude, longitude, altitude, speed, distance, etc.

        activity_lap: Lap-level metrics for activities (running, cycling, etc.).
            Additional columns: lapIndex, lapDuration, lapDistance, avgHR, maxHR, avgSpeed, calories, etc.

        activity_session: Session-level metrics aggregating entire activities.
            Additional columns: sessionIndex, totalDuration, totalDistance, avgHR, maxHR, totalCalories, etc.

        activity_summary: Summary of completed activities with key metrics.
            Additional columns (24 total):
            - ActivityID, Activity_ID: Unique activity identifiers
            - activityName, activityType: Activity name and type (e.g., 'strength_training', 'other')
            - averageHR, maxHR: Heart rate metrics (bpm)
            - averageSpeed: Average speed during activity
            - calories, bmrCalories: Total calories and basal metabolic rate calories
            - distance: Distance covered (meters)
            - elapsedDuration, movingDuration: Time metrics (seconds)
            - hrTimeInZone_1 through hrTimeInZone_5: Time spent in each HR zone (seconds)
            - lapCount: Number of laps in the activity
            Note: 'END' entries mark activity completion and have NaN values for metrics.

        body_battery_intraday: Body battery energy levels throughout the day.
            Additional columns:
            - BodyBatteryLevel: Energy reserve level (0-100 scale)
                * Charges during rest/sleep (relaxation, recovery)
                * Drains during activity and stress
                * Higher values indicate more energy reserves
            Typical sampling: Every 3-5 minutes during waking hours.

        breathing_rate_intraday: Respiratory rate measurements.
            Additional columns:
            - BreathingRate: Breaths per minute (typically 8-20 bpm)
            Typical sampling: Every 2 minutes.

        daily_stats: Comprehensive daily health and activity statistics.
            Additional columns (46 total):
            Activity metrics:
            - activeKilocalories, bmrKilocalories: Active and basal calories
            - activeSeconds, sedentarySeconds, sleepingSeconds: Time allocation
            - totalSteps, totalDistanceMeters: Movement totals
            - floorsAscended/Descended, floorsAscended/DescendedInMeters: Elevation changes
            - moderateIntensityMinutes, vigorousIntensityMinutes: Exercise intensity

            Heart rate metrics:
            - restingHeartRate: RHR (bpm)
            - minHeartRate, maxHeartRate: Daily extremes
            - minAvgHeartRate, maxAvgHeartRate: Averaged extremes

            Stress metrics (all in seconds and percentages):
            - restStressDuration, restStressPercentage: Time in resting/recovery state (low stress)
            - lowStressDuration, lowStressPercentage: Low stress periods
            - mediumStressDuration, mediumStressPercentage: Medium stress periods
            - highStressDuration, highStressPercentage: High stress periods
            - activityStressDuration, activityStressPercentage: Stress during physical activity
            - uncategorizedStressDuration, uncategorizedStressPercentage: Uncategorized periods
            - stressDuration, stressPercentage, totalStressDuration: Aggregate stress metrics

            Body battery metrics:
            - bodyBatteryAtWakeTime, bodyBatteryHighestValue, bodyBatteryLowestValue: Daily body battery levels
            - bodyBatteryChargedValue, bodyBatteryDrainedValue: Net charge/drain
            - bodyBatteryDuringSleep: Body battery level during sleep

            SpO2 metrics:
            - averageSpo2, lowestSpo2: Blood oxygen saturation (percentage)

        hrv_intraday: Heart rate variability measurements during sleep/rest.
            Additional columns:
            - hrvValue: HRV in milliseconds (higher values indicate better recovery)
            Typical sampling: Every 5 minutes during sleep.

        heart_rate_intraday: Continuous heart rate monitoring.
            Additional columns:
            - HeartRate: Heart rate in beats per minute (bpm)
            Typical sampling: Every 2 minutes during activity, less frequent at rest.

        race_predictions: AI-predicted race finish times based on fitness level.
            Additional columns:
            - time5K, time10K, timeHalfMarathon, timeMarathon: Predicted finish times (seconds)
            Updated daily based on recent training and fitness trends.

        sleep_intraday: Detailed sleep tracking with multiple physiological signals.
            Additional columns (15 total):
            Movement and stages:
            - SleepMovementActivityLevel: Movement intensity (arbitrary units, higher = more movement)
            - SleepMovementActivitySeconds: Duration of movement period (typically 60s)
            - SleepStageLevel: Sleep stage identifier (awake/light/deep/REM)
            - SleepStageSeconds: Duration in current stage (typically 60s)

            Physiological metrics during sleep:
            - bodyBattery: Body battery level (0-100)
            - heartRate: Heart rate (bpm)
            - hrvData: Heart rate variability (ms)
            - respirationValue: Breathing rate (breaths per minute)
            - spo2Reading: Blood oxygen saturation (percentage)
            - stressValue: Stress level (0-100)
            - sleepRestlessValue: Restlessness indicator

            Note: Many fields may be NaN depending on measurement availability at that time.
            Typical sampling: Every 1 minute throughout sleep period.

        sleep_summary: Nightly sleep summary with totals and averages.
            Additional columns (22 total):
            Sleep duration metrics (all in seconds):
            - sleepTimeSeconds: Total sleep time
            - awakeSleepSeconds: Time awake during sleep period
            - lightSleepSeconds, deepSleepSeconds, remSleepSeconds: Time in each sleep stage

            Sleep quality metrics:
            - sleepScore: Overall sleep quality score (0-100)
            - awakeCount: Number of times awake during night
            - restlessMomentsCount: Number of restless periods

            Physiological averages during sleep:
            - restingHeartRate: Resting HR during sleep (bpm)
            - averageRespirationValue, lowestRespirationValue, highestRespirationValue: Breathing rate (bpm)
            - averageSpO2Value, lowestSpO2Value, highestSpO2Value: Blood oxygen (percentage)
            - avgOvernightHrv: Average HRV during sleep (ms)
            - avgSleepStress: Average stress during sleep (0-100)

            - bodyBatteryChange: Net body battery change during sleep (positive = charging)

        steps_intraday: Step count measurements at regular intervals.
            Additional columns:
            - StepsCount: Number of steps in the interval
            Typical sampling: Every 15 minutes.

        stress_intraday: Continuous stress level monitoring.
            Additional columns:
            - stressLevel: Stress level (0-100 scale)
                * 0-25: Resting/recovery state (rest period, not negative stress)
                * 26-50: Low stress
                * 51-75: Medium stress
                * 76-100: High stress
                * Note: Lower values during rest indicate recovery, not absence of stress
            Typical sampling: Every 3 minutes.
    """

    activity_gps: Optional[pd.DataFrame] = None
    activity_lap: Optional[pd.DataFrame] = None
    activity_session: Optional[pd.DataFrame] = None
    activity_summary: Optional[pd.DataFrame] = None
    body_battery_intraday: Optional[pd.DataFrame] = None
    breathing_rate_intraday: Optional[pd.DataFrame] = None
    daily_stats: Optional[pd.DataFrame] = None
    hrv_intraday: Optional[pd.DataFrame] = None
    heart_rate_intraday: Optional[pd.DataFrame] = None
    race_predictions: Optional[pd.DataFrame] = None
    sleep_intraday: Optional[pd.DataFrame] = None
    sleep_summary: Optional[pd.DataFrame] = None
    steps_intraday: Optional[pd.DataFrame] = None
    stress_intraday: Optional[pd.DataFrame] = None


class InfluxDBGarminDataExporter:
    """Exports Garmin data from docker container and returns pandas DataFrames."""

    def __init__(
        self,
        docker_container_name: str = "garmin-fetch-data",
        project_root: Path = Path("/Users/zbigi/projects/garmin-grafana"),
    ):
        self.docker_container_name = docker_container_name
        self.project_root = project_root
        # Dependencies for testability
        self._runner: AsyncCommandRunner = SubprocessRunner()
        self._lock = AsyncFileLock(self.project_root / ".garmin_fetch.lock", timeout_s=15 * 60)
        # Retry tuning for compose runs (transient DNS/network races)
        self._compose_max_retries = 3
        self._compose_initial_delay_s = 10.0
        self._compose_backoff = 2.0

    # Dependency injection helpers (optional for tests)
    def with_runner(self, runner: AsyncCommandRunner) -> "InfluxDBGarminDataExporter":
        self._runner = runner
        return self

    def with_lock(self, lock: AsyncFileLock) -> "InfluxDBGarminDataExporter":
        self._lock = lock
        return self

    async def _execute_docker_command_with_retry(
        self,
        cmd: list[str],
        operation_name: str,
        max_retries: int | None = None,
    ) -> CommandResult:
        """Execute a docker command with exponential backoff retry on transient errors.

        Args:
            cmd: Command to execute
            operation_name: Human-readable operation name for logging
            max_retries: Maximum retry attempts (defaults to self._compose_max_retries)

        Returns:
            CommandResult with stdout, stderr, and return code

        Raises:
            subprocess.CalledProcessError: If all retry attempts fail
        """
        max_retries = max_retries if max_retries is not None else self._compose_max_retries
        delay = self._compose_initial_delay_s
        last_result: CommandResult | None = None

        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                logger.info(
                    "Retrying {} (attempt {}/{})",
                    operation_name,
                    attempt,
                    max_retries,
                )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await proc.communicate()
            out = stdout_b.decode() if isinstance(stdout_b, (bytes, bytearray)) else (stdout_b or "")
            err = stderr_b.decode() if isinstance(stderr_b, (bytes, bytearray)) else (stderr_b or "")
            result = CommandResult(proc.returncode or 0, out, err)
            last_result = result

            if result.returncode == 0:
                logger.debug("{} completed successfully", operation_name)
                return result

            # Log failure and decide whether to retry
            logger.warning(
                "{} failed (code {}): {}",
                operation_name,
                result.returncode,
                (result.stderr.strip()[:500] + ("…" if len(result.stderr.strip()) > 500 else "")),
            )

            if attempt < max_retries and self._is_transient_error(result.stderr):
                logger.info("Waiting {:.1f}s before retrying {}…", delay, operation_name)
                await asyncio.sleep(delay)
                delay *= self._compose_backoff
                continue
            break

        # All attempts failed
        assert last_result is not None
        raise subprocess.CalledProcessError(
            last_result.returncode,
            cmd,
            output=last_result.stdout,
            stderr=last_result.stderr,
        )

    @staticmethod
    def _build_compose_command(start_date: date, end_date: Optional[date]) -> list[str]:
        cmd = [
            "docker",
            "compose",
            "run",
            "--rm",
            "-e",
            f"MANUAL_START_DATE={start_date.isoformat()}",
        ]
        if end_date:
            cmd.extend(["-e", f"MANUAL_END_DATE={end_date.isoformat()}"])
        cmd.append("garmin-fetch-data")
        return cmd

    @staticmethod
    def _is_transient_error(err: str) -> bool:
        if not err:
            return False
        err_l = err.lower()
        transient_tokens = [
            "name or service not known",
            "failed to resolve",
            "max retries exceeded",
            "connection refused",
            "network is unreachable",
        ]
        return any(tok in err_l for tok in transient_tokens)

    async def refresh_influxdb_data(self, start_date: date, end_date: Optional[date] = None) -> None:
        """
        Run docker compose run --rm -e MANUAL_START_DATE=<> -e MANUAL_END_DATE=<> garmin-fetch-data
        :return:
        """
        update_command = self._build_compose_command(start_date, end_date)

        # Serialize access to docker compose run across processes (async, testable)
        async with self._lock:
            delay = self._compose_initial_delay_s
            last_result: Optional[CommandResult] = None
            for attempt in range(1, self._compose_max_retries + 1):
                if attempt > 1:
                    logger.info(
                        "Retrying docker compose run for Garmin fetch (attempt {}/{})",
                        attempt,
                        self._compose_max_retries,
                    )

                result = await self._runner.run(update_command, cwd=self.project_root)
                last_result = result
                if result.returncode == 0:
                    logger.info(f"Successfully refreshed InfluxDB data from {start_date} to {end_date or 'latest'}")
                    logger.debug(f"Update command output: {result.stdout}")
                    return

                # Decide whether to retry
                logger.warning(
                    "Failed to refresh InfluxDB data (code {}): {}",
                    result.returncode,
                    (result.stderr.strip()[:500] + ("…" if len(result.stderr.strip()) > 500 else "")),
                )

                if attempt < self._compose_max_retries and self._is_transient_error(result.stderr):
                    logger.info("Waiting {:.1f}s before retrying Garmin fetch…", delay)
                    await asyncio.sleep(delay)
                    delay *= self._compose_backoff
                    continue
                break

        # If we reach here, all attempts failed
        err_out = last_result.stderr if last_result else ""
        raise subprocess.CalledProcessError(1, update_command, output=err_out, stderr=err_out)

    async def export_data(self, days: int = 7) -> GarminExportData:
        """Export Garmin health data from InfluxDB for the specified time period.

        This method executes a series of docker commands to:
        1. Run the influxdb_exporter.py script inside the garmin-fetch-data container (with retry)
        2. Copy the generated ZIP file containing CSV exports (with retry)
        3. Extract and parse all CSV files into pandas DataFrames

        Docker commands are executed with automatic retry on transient network errors
        (DNS failures, connection refused, etc.) using exponential backoff.

        The exported data includes comprehensive health metrics from Garmin devices:
        - Activity data (GPS, laps, sessions, summaries)
        - Physiological metrics (heart rate, HRV, breathing rate, SpO2)
        - Sleep tracking (stages, quality, physiological data during sleep)
        - Daily statistics (steps, calories, stress, activity levels)
        - Body battery energy tracking
        - Race performance predictions

        Args:
            days: Number of days to export data for (default: 7)
                 Data is exported from (today - days) to today

        Returns:
            GarminExportData: Dataclass containing pandas DataFrames with exported data.
                See GarminExportData docstring for detailed column descriptions.
                Individual DataFrames may be None if no data is available for that metric.

        Raises:
            subprocess.CalledProcessError: If docker commands fail after all retry attempts
            ValueError: If the zip filename cannot be extracted from docker output
            Exception: If CSV parsing fails for any exported file

        Example:
            >>> exporter = InfluxDBGarminDataExporter()
            >>> data = await exporter.export_data(days=7)
            >>> if data.sleep_summary is not None:
            ...     avg_sleep_score = data.sleep_summary['sleepScore'].mean()
            ...     print(f"Average sleep score: {avg_sleep_score}")
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Step 1: Execute docker command to export data with retry logic
            export_cmd = [
                "docker",
                "exec",
                self.docker_container_name,
                "uv",
                "run",
                "/app/garmin_grafana/influxdb_exporter.py",
                f"--last-n-days={days}",
            ]

            result = await self._execute_docker_command_with_retry(
                export_cmd,
                operation_name="Garmin data export",
            )

            # Extract zip filename from output
            zip_filename = self._extract_zip_filename(result.stdout)
            if not zip_filename:
                raise ValueError("Could not find zip filename in docker output")

            # Step 2: Copy zip file from container to temp directory with retry logic
            temp_zip_path = os.path.join(temp_dir, zip_filename)
            copy_cmd = ["docker", "cp", f"{self.docker_container_name}:/tmp/{zip_filename}", temp_zip_path]
            await self._execute_docker_command_with_retry(
                copy_cmd,
                operation_name="Docker copy export file",
            )

            # Step 3: Extract zip file
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            unzip_cmd = ["unzip", temp_zip_path, "-d", extract_dir]
            proc = await asyncio.create_subprocess_exec(
                *unzip_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode() if isinstance(stderr, (bytes, bytearray)) else (stderr or "")
                logger.error(f"Unzip failed (code {proc.returncode}): {err}")
                raise subprocess.CalledProcessError(proc.returncode, unzip_cmd, stderr=err)

            # Step 4: Load CSV files into pandas DataFrames
            return self._load_csv_files(extract_dir)

    @staticmethod
    def _extract_zip_filename(docker_output: str) -> Optional[str]:
        """Extract zip filename from docker command output."""
        lines = docker_output.split("\n")
        for line in lines:
            if "Exported" in line and ".zip" in line:
                # Extract filename from path like /tmp/GarminStats_Export_20250526_192750_Last7Days.zip
                start = line.find("/tmp/") + 5
                end = line.find(".zip") + 4
                if 4 < start < end:
                    return line[start:end]
        return None

    @staticmethod
    def _load_csv_files(extract_dir: str) -> GarminExportData:
        """Load CSV files from extracted directory into DataFrames."""
        csv_files = {
            "activity_gps": "ActivityGPS.csv",
            "activity_lap": "ActivityLap.csv",
            "activity_session": "ActivitySession.csv",
            "activity_summary": "ActivitySummary.csv",
            "body_battery_intraday": "BodyBatteryIntraday.csv",
            "breathing_rate_intraday": "BreathingRateIntraday.csv",
            "daily_stats": "DailyStats.csv",
            "hrv_intraday": "HRV_Intraday.csv",
            "heart_rate_intraday": "HeartRateIntraday.csv",
            "race_predictions": "RacePredictions.csv",
            "sleep_intraday": "SleepIntraday.csv",
            "sleep_summary": "SleepSummary.csv",
            "steps_intraday": "StepsIntraday.csv",
            "stress_intraday": "StressIntraday.csv",
        }

        data = {}
        for attr_name, csv_filename in csv_files.items():
            csv_path = os.path.join(extract_dir, csv_filename)
            if os.path.exists(csv_path):
                try:
                    df = pd.read_csv(csv_path)
                    data[attr_name] = df if not df.empty else None
                except Exception as e:
                    logger.error(f"Warning: Could not load {csv_filename}: {e}")
                    data[attr_name] = None
            else:
                data[attr_name] = None

        return GarminExportData(**data)
