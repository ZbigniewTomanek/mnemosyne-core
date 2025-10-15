import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from loguru import logger


@dataclass
class FoodLogEntry:
    name: str
    protein: str
    carbs: str
    fats: str
    comment: str
    datetime: Optional[str] = None


@dataclass
class DrugLogEntry:
    drug_name: str
    dosage: int
    datetime: Optional[str] = None


class MessageType(Enum):
    TEXT = "text"
    VOICE = "voice"


@dataclass
class MessageEntry:
    user_id: int
    message_type: MessageType
    content: str
    response: str
    datetime: Optional[str] = None


@dataclass
class CorrelationRunEntry:
    run_id: str
    user_id: int
    started_at: datetime
    completed_at: datetime
    window_days: int
    config_json: str


@dataclass
class CorrelationEventEntry:
    run_id: str
    event_id: str
    source: str
    title: str
    start: datetime
    end: datetime
    metadata_json: Optional[str] = None
    supporting_json: Optional[str] = None


@dataclass
class CorrelationMetricEntry:
    run_id: str
    event_id: str
    metric: str
    effect_size: float
    effect_direction: str
    confidence: float
    p_value: float
    sample_count: int
    baseline_mean: Optional[float] = None
    post_event_mean: Optional[float] = None
    notes: Optional[str] = None
    is_triggered: bool = True


@dataclass(frozen=True)
class CorrelationMetricRecord:
    metric: str
    effect_size: float
    effect_direction: str
    confidence: float
    p_value: Optional[float]
    sample_count: int
    baseline_mean: Optional[float]
    post_event_mean: Optional[float]
    notes: Optional[str]


@dataclass(frozen=True)
class CorrelationEventRecord:
    run_id: str
    event_id: str
    source: str
    title: str
    start: datetime
    end: datetime
    categories: tuple[str, ...]
    metadata: dict[str, Any]
    supporting_evidence: dict[str, Any]
    metrics: tuple[CorrelationMetricRecord, ...]
    run_started_at: datetime
    run_completed_at: datetime
    run_window_days: int
    run_config: dict[str, Any]


@dataclass(frozen=True)
class MetricObservationRecord:
    run_id: str
    event_id: str
    title: str
    source: str
    metric: str
    effect_size: float
    is_triggered: bool
    observed_at: datetime
    categories: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass
class ActivityImpactVarianceEntry:
    variance_id: str
    run_id: str
    event_id: str
    title_key: str
    raw_title: str
    metric: str
    window_start: datetime
    window_end: datetime
    baseline_mean: float
    baseline_stddev: float
    baseline_sample_count: int
    current_effect: float
    delta: float
    normalised_score: float
    trend: str
    metadata_json: Optional[str] = None
    created_at: Optional[datetime] = None
    config_hash: str = ""


class DBService:
    _FOOD_LOG_TABLE_NAME = "food_log"
    _DRUG_LOG_TABLE_NAME = "drug_log"
    _MESSAGE_LOG_TABLE_NAME = "message_log"
    _CORRELATION_RUNS_TABLE = "correlation_runs"
    _CORRELATION_EVENTS_TABLE = "correlation_events"
    _CORRELATION_METRICS_TABLE = "correlation_metric_effects"
    _ACTIVITY_VARIANCE_TABLE = "correlation_activity_variance"

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self._initialize_tables()

    def _initialize_tables(self) -> None:
        """Initialize all database tables on service creation."""
        logger.info("Initializing database tables")
        with self._get_connection() as conn:
            # Initialize food log table
            create_food_table_query = f"""
            CREATE TABLE IF NOT EXISTS {self._FOOD_LOG_TABLE_NAME} (
                name VARCHAR,
                protein VARCHAR,
                carbs VARCHAR,
                fats VARCHAR,
                comment VARCHAR,
                datetime TIMESTAMP
            )
            """
            # Initialize drug log table
            create_drug_table_query = f"""
            CREATE TABLE IF NOT EXISTS {self._DRUG_LOG_TABLE_NAME} (
                name VARCHAR,
                dosage INT,
                datetime TIMESTAMP
            )
            """
            # Initialize message log table
            create_message_table_query = f"""
            CREATE TABLE IF NOT EXISTS {self._MESSAGE_LOG_TABLE_NAME} (
                user_id INT,
                message_type VARCHAR,
                content TEXT,
                response TEXT,
                datetime TIMESTAMP
            )
            """
            create_correlation_runs_query = f"""
            CREATE TABLE IF NOT EXISTS {self._CORRELATION_RUNS_TABLE} (
                run_id TEXT PRIMARY KEY,
                user_id INT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                window_days INT,
                config_json TEXT
            )
            """
            create_correlation_events_query = f"""
            CREATE TABLE IF NOT EXISTS {self._CORRELATION_EVENTS_TABLE} (
                run_id TEXT,
                event_id TEXT,
                source TEXT,
                title TEXT,
                start TIMESTAMP,
                end TIMESTAMP
            )
            """
            create_correlation_metrics_query = f"""
            CREATE TABLE IF NOT EXISTS {self._CORRELATION_METRICS_TABLE} (
                run_id TEXT,
                event_id TEXT,
                metric TEXT,
                effect_size REAL,
                effect_direction TEXT,
                confidence REAL,
                p_value REAL,
                sample_count INT,
                baseline_mean REAL,
                post_event_mean REAL
            )
            """
            create_activity_variance_query = f"""
            CREATE TABLE IF NOT EXISTS {self._ACTIVITY_VARIANCE_TABLE} (
                variance_id TEXT PRIMARY KEY,
                run_id TEXT,
                event_id TEXT,
                title_key TEXT,
                raw_title TEXT,
                metric TEXT,
                window_start TIMESTAMP,
                window_end TIMESTAMP,
                baseline_mean REAL,
                baseline_stddev REAL,
                baseline_sample_count INT,
                current_effect REAL,
                delta REAL,
                normalised_score REAL,
                trend TEXT,
                metadata_json TEXT,
                created_at TIMESTAMP,
                config_hash TEXT
            )
            """
            conn.execute(create_food_table_query)
            conn.execute(create_drug_table_query)
            conn.execute(create_message_table_query)
            conn.execute(create_correlation_runs_query)
            conn.execute(create_correlation_events_query)
            conn.execute(create_correlation_metrics_query)
            conn.execute(create_activity_variance_query)
            self._ensure_column(conn, self._CORRELATION_EVENTS_TABLE, "metadata_json", "TEXT")
            self._ensure_column(conn, self._CORRELATION_EVENTS_TABLE, "supporting_json", "TEXT")
            self._ensure_column(conn, self._CORRELATION_METRICS_TABLE, "notes", "TEXT")
            self._ensure_column(conn, self._CORRELATION_METRICS_TABLE, "is_triggered", "INT DEFAULT 1")
            self._ensure_column(conn, self._ACTIVITY_VARIANCE_TABLE, "config_hash", "TEXT")

            # Create indexes for performance optimization
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_events_start_date
                ON {self._CORRELATION_EVENTS_TABLE}(start)
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_events_title
                ON {self._CORRELATION_EVENTS_TABLE}(title)
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_metrics_event_metric
                ON {self._CORRELATION_METRICS_TABLE}(event_id, metric)
                """
            )

            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        existing_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column in existing_columns:
            return
        logger.info("Adding column '{}' to table '{}'", column, table)
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def add_food_log_entry(self, entry: FoodLogEntry) -> None:
        logger.info(f"Adding food log entry: {entry}")
        with self._get_connection() as conn:
            insert_query = f"""
            INSERT INTO {self._FOOD_LOG_TABLE_NAME} (name, protein, carbs, fats, comment, datetime)
            VALUES (
                '{entry.name}',
                '{entry.protein}',
                '{entry.carbs}',
                '{entry.fats}',
                '{entry.comment}',
                CURRENT_TIMESTAMP
            )
            """
            conn.execute(insert_query)
            conn.commit()

    def add_drug_log_entry(self, entry: DrugLogEntry) -> None:
        logger.info(f"Adding drug log entry: {entry}")
        with self._get_connection() as conn:
            insert_query = f"""
            INSERT INTO {self._DRUG_LOG_TABLE_NAME} (name, dosage, datetime)
            VALUES ('{entry.drug_name}', {entry.dosage}, CURRENT_TIMESTAMP)
            """
            conn.execute(insert_query)
            conn.commit()

    def list_food_logs(self, limit: Optional[int] = None) -> list[FoodLogEntry]:
        logger.info("Listing food logs")
        with self._get_connection() as conn:
            query = f"""SELECT
             name, protein, carbs, fats, comment, datetime
            FROM {self._FOOD_LOG_TABLE_NAME} ORDER BY datetime DESC"""
            if limit is not None:
                query += f" LIMIT {limit}"
            for row in conn.execute(query).fetchall():
                yield FoodLogEntry(*row)

    def list_drug_logs(self, limit: Optional[int] = None) -> list[DrugLogEntry]:
        logger.info("Listing drug logs")
        with self._get_connection() as conn:
            query = f"""SELECT
             name, dosage, datetime
            FROM {self._DRUG_LOG_TABLE_NAME} ORDER BY datetime DESC"""
            if limit is not None:
                query += f" LIMIT {limit}"
            for row in conn.execute(query).fetchall():
                yield DrugLogEntry(*row)

    def add_message_entry(self, entry: MessageEntry) -> None:
        logger.info(f"Adding message log entry: {entry}")
        with self._get_connection() as conn:
            insert_query = f"""
            INSERT INTO {self._MESSAGE_LOG_TABLE_NAME} (user_id, message_type, content, response, datetime)
            VALUES (
                {entry.user_id},
                '{entry.message_type.value}',
                ?,
                ?,
                CURRENT_TIMESTAMP
            )
            """
            conn.execute(insert_query, (entry.content, entry.response))
            conn.commit()

    def list_message_logs(self, user_id: Optional[int] = None, limit: Optional[int] = None) -> list[MessageEntry]:
        logger.info(f"Listing message logs for user_id: {user_id}")
        with self._get_connection() as conn:
            query = f"""SELECT
             user_id, message_type, content, response, datetime
            FROM {self._MESSAGE_LOG_TABLE_NAME}"""

            conditions = []
            if user_id is not None:
                conditions.append(f"user_id = {user_id}")

            if conditions:
                query += f" WHERE {' AND '.join(conditions)}"

            query += " ORDER BY datetime DESC"

            if limit is not None:
                query += f" LIMIT {limit}"

            for row in conn.execute(query).fetchall():
                user_id, message_type_str, content, response, datetime_str = row
                message_type = MessageType(message_type_str)
                yield MessageEntry(user_id, message_type, content, response, datetime_str)

    def add_correlation_run(self, entry: CorrelationRunEntry) -> None:
        logger.info(f"Persisting correlation run {entry.run_id}")
        with self._get_connection() as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {self._CORRELATION_RUNS_TABLE}
                (run_id, user_id, started_at, completed_at, window_days, config_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.run_id,
                    entry.user_id,
                    entry.started_at.isoformat(),
                    entry.completed_at.isoformat(),
                    entry.window_days,
                    entry.config_json,
                ),
            )
            conn.commit()

    def add_correlation_event(self, entry: CorrelationEventEntry) -> None:
        logger.info(f"Persisting correlation event {entry.event_id} (run {entry.run_id})")
        with self._get_connection() as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {self._CORRELATION_EVENTS_TABLE}
                (run_id, event_id, source, title, start, end, metadata_json, supporting_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.run_id,
                    entry.event_id,
                    entry.source,
                    entry.title,
                    entry.start.isoformat(),
                    entry.end.isoformat(),
                    entry.metadata_json,
                    entry.supporting_json,
                ),
            )
            conn.commit()

    def add_correlation_metric(self, entry: CorrelationMetricEntry) -> None:
        logger.info(f"Persisting correlation metric {entry.metric} for event {entry.event_id} (run {entry.run_id})")
        with self._get_connection() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._CORRELATION_METRICS_TABLE}
                (run_id, event_id, metric, effect_size, effect_direction, confidence, p_value, sample_count,
                 baseline_mean, post_event_mean, notes, is_triggered)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.run_id,
                    entry.event_id,
                    entry.metric,
                    entry.effect_size,
                    entry.effect_direction,
                    entry.confidence,
                    entry.p_value,
                    entry.sample_count,
                    entry.baseline_mean,
                    entry.post_event_mean,
                    entry.notes,
                    1 if entry.is_triggered else 0,
                ),
            )
            conn.commit()

    def correlation_metric_exists(
        self,
        *,
        event_id: str,
        metric: str,
    ) -> bool:
        """Return True if a correlation metric already exists for the event."""

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT 1 FROM {self._CORRELATION_METRICS_TABLE}
                WHERE event_id = ? AND metric = ?
                LIMIT 1
                """,
                (event_id, metric),
            )
            return cursor.fetchone() is not None

    def fetch_metric_observations(self, *, lookback_days: int) -> list[MetricObservationRecord]:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        cutoff_iso = cutoff.isoformat()

        query = f"""
            SELECT
                m.run_id,
                m.event_id,
                e.title,
                e.source,
                e.metadata_json,
                e.start,
                m.metric,
                m.effect_size,
                m.is_triggered
            FROM {self._CORRELATION_METRICS_TABLE} AS m
            INNER JOIN {self._CORRELATION_EVENTS_TABLE} AS e ON e.event_id = m.event_id AND e.run_id = m.run_id
            WHERE e.start >= ?
        """

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, (cutoff_iso,)).fetchall()

        observations: list[MetricObservationRecord] = []
        for row in rows:
            metadata_payload: dict[str, Any] = {}
            if row["metadata_json"]:
                try:
                    metadata_payload = json.loads(row["metadata_json"])
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to decode correlation event metadata for metric observation {}/{}",
                        row["run_id"],
                        row["event_id"],
                    )
            categories = tuple(sorted(metadata_payload.get("categories") or []))
            metadata = metadata_payload.get("metadata") or {}
            observations.append(
                MetricObservationRecord(
                    run_id=row["run_id"],
                    event_id=row["event_id"],
                    title=row["title"],
                    source=row["source"],
                    metric=row["metric"],
                    effect_size=float(row["effect_size"]),
                    is_triggered=bool(row["is_triggered"]),
                    observed_at=_to_datetime(row["start"]),
                    categories=categories,
                    metadata=metadata,
                )
            )

        return observations

    def add_activity_variance(self, entry: ActivityImpactVarianceEntry) -> None:
        created_at = entry.created_at or datetime.now(UTC)
        logger.info(
            "Persisting activity variance {} for event {} ({})",
            entry.metric,
            entry.event_id,
            entry.title_key,
        )
        with self._get_connection() as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {self._ACTIVITY_VARIANCE_TABLE}
                (variance_id, run_id, event_id, title_key, raw_title, metric, window_start, window_end,
                 baseline_mean, baseline_stddev, baseline_sample_count, current_effect, delta, normalised_score,
                 trend, metadata_json, created_at, config_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.variance_id,
                    entry.run_id,
                    entry.event_id,
                    entry.title_key,
                    entry.raw_title,
                    entry.metric,
                    entry.window_start.isoformat(),
                    entry.window_end.isoformat(),
                    entry.baseline_mean,
                    entry.baseline_stddev,
                    entry.baseline_sample_count,
                    entry.current_effect,
                    entry.delta,
                    entry.normalised_score,
                    entry.trend,
                    entry.metadata_json,
                    created_at.isoformat(),
                    entry.config_hash,
                ),
            )
            conn.commit()

    def activity_variance_exists(self, *, event_id: str, metric: str, config_hash: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT 1 FROM {self._ACTIVITY_VARIANCE_TABLE}
                WHERE event_id = ? AND metric = ? AND config_hash = ?
                LIMIT 1
                """,
                (event_id, metric, config_hash),
            )
            return cursor.fetchone() is not None

    def get_activity_variance(
        self,
        *,
        event_id: str,
        metric: str,
        config_hash: str,
    ) -> ActivityImpactVarianceEntry | None:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT
                    variance_id,
                    run_id,
                    event_id,
                    title_key,
                    raw_title,
                    metric,
                    window_start,
                    window_end,
                    baseline_mean,
                    baseline_stddev,
                    baseline_sample_count,
                    current_effect,
                    delta,
                    normalised_score,
                    trend,
                    metadata_json,
                    created_at,
                    config_hash
                FROM {self._ACTIVITY_VARIANCE_TABLE}
                WHERE event_id = ? AND metric = ? AND config_hash = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (event_id, metric, config_hash),
            ).fetchone()

        if row is None:
            return None

        return ActivityImpactVarianceEntry(
            variance_id=row["variance_id"],
            run_id=row["run_id"],
            event_id=row["event_id"],
            title_key=row["title_key"],
            raw_title=row["raw_title"],
            metric=row["metric"],
            window_start=_to_datetime(row["window_start"]),
            window_end=_to_datetime(row["window_end"]),
            baseline_mean=float(row["baseline_mean"]),
            baseline_stddev=float(row["baseline_stddev"]),
            baseline_sample_count=int(row["baseline_sample_count"]),
            current_effect=float(row["current_effect"]),
            delta=float(row["delta"]),
            normalised_score=float(row["normalised_score"]),
            trend=row["trend"],
            metadata_json=row["metadata_json"],
            created_at=_to_datetime(row["created_at"]) if row["created_at"] else None,
            config_hash=row["config_hash"],
        )

    def fetch_activity_variances(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        limit: int | None,
        min_score: float,
    ) -> list[ActivityImpactVarianceEntry]:
        """Return variance entries filtered by window range and score."""

        query = f"""
            SELECT
                variance_id,
                run_id,
                event_id,
                title_key,
                raw_title,
                metric,
                window_start,
                window_end,
                baseline_mean,
                baseline_stddev,
                baseline_sample_count,
                current_effect,
                delta,
                normalised_score,
                trend,
                metadata_json,
                created_at,
                config_hash
            FROM {self._ACTIVITY_VARIANCE_TABLE}
            WHERE 1 = 1
        """
        params: list[Any] = []

        if start_date is not None:
            start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
            query += " AND window_end >= ?"
            params.append(start_dt.isoformat())

        if end_date is not None:
            end_exclusive = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            query += " AND window_end < ?"
            params.append(end_exclusive.isoformat())

        if min_score > 0:
            query += " AND ABS(normalised_score) >= ?"
            params.append(min_score)

        query += " ORDER BY ABS(normalised_score) DESC, created_at DESC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        results: list[ActivityImpactVarianceEntry] = []
        for row in rows:
            results.append(
                ActivityImpactVarianceEntry(
                    variance_id=row["variance_id"],
                    run_id=row["run_id"],
                    event_id=row["event_id"],
                    title_key=row["title_key"],
                    raw_title=row["raw_title"],
                    metric=row["metric"],
                    window_start=_to_datetime(row["window_start"]),
                    window_end=_to_datetime(row["window_end"]),
                    baseline_mean=float(row["baseline_mean"]),
                    baseline_stddev=float(row["baseline_stddev"]),
                    baseline_sample_count=int(row["baseline_sample_count"]),
                    current_effect=float(row["current_effect"]),
                    delta=float(row["delta"]),
                    normalised_score=float(row["normalised_score"]),
                    trend=row["trend"],
                    metadata_json=row["metadata_json"],
                    created_at=_to_datetime(row["created_at"]) if row["created_at"] else None,
                    config_hash=row["config_hash"],
                )
            )

        return results

    def fetch_correlation_events(
        self,
        *,
        lookback_days: int,
        limit: Optional[int] = None,
        sources: Optional[set[str]] = None,
    ) -> list[CorrelationEventRecord]:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        cutoff_iso = cutoff.isoformat()

        params: list[Any] = [cutoff_iso]
        source_filter = ""
        if sources:
            placeholders = ",".join("?" for _ in sources)
            source_filter = f" AND e.source IN ({placeholders})"
            params.extend(sorted(sources))

        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ?"
            params.append(limit)

        query = f"""
            SELECT
                e.run_id,
                e.event_id,
                e.source,
                e.title,
                e.start,
                e.end,
                e.metadata_json,
                e.supporting_json,
                r.started_at,
                r.completed_at,
                r.window_days,
                r.config_json
            FROM {self._CORRELATION_EVENTS_TABLE} AS e
            INNER JOIN {self._CORRELATION_RUNS_TABLE} AS r ON r.run_id = e.run_id
            WHERE e.start >= ?{source_filter}
            ORDER BY e.start DESC{limit_clause}
            """

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            if not rows:
                return []

            run_ids = sorted({row["run_id"] for row in rows})
            placeholder = ",".join("?" for _ in run_ids)
            metrics_query = f"""
                SELECT
                    run_id,
                    event_id,
                    metric,
                    effect_size,
                    effect_direction,
                    confidence,
                    p_value,
                    sample_count,
                    baseline_mean,
                    post_event_mean,
                    notes
                FROM {self._CORRELATION_METRICS_TABLE}
                WHERE run_id IN ({placeholder}) AND is_triggered = 1
                """
            metric_rows = conn.execute(metrics_query, run_ids).fetchall()

        metrics_map: dict[tuple[str, str], list[CorrelationMetricRecord]] = {}
        for metric_row in metric_rows:
            key = (metric_row["run_id"], metric_row["event_id"])
            metric_record = CorrelationMetricRecord(
                metric=metric_row["metric"],
                effect_size=float(metric_row["effect_size"]),
                effect_direction=metric_row["effect_direction"],
                confidence=float(metric_row["confidence"]),
                p_value=float(metric_row["p_value"]) if metric_row["p_value"] is not None else None,
                sample_count=int(metric_row["sample_count"]),
                baseline_mean=float(metric_row["baseline_mean"]) if metric_row["baseline_mean"] is not None else None,
                post_event_mean=(
                    float(metric_row["post_event_mean"]) if metric_row["post_event_mean"] is not None else None
                ),
                notes=metric_row["notes"],
            )
            metrics_map.setdefault(key, []).append(metric_record)

        records: list[CorrelationEventRecord] = []
        for row in rows:
            metadata_payload: dict[str, Any] = {}
            if row["metadata_json"]:
                try:
                    metadata_payload = json.loads(row["metadata_json"])
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to decode correlation event metadata for event {}/{}", row["run_id"], row["event_id"]
                    )
            categories = metadata_payload.get("categories") or []
            metadata = metadata_payload.get("metadata") or {}

            supporting_evidence: dict[str, Any] = {}
            if row["supporting_json"]:
                try:
                    supporting_evidence = json.loads(row["supporting_json"])
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to decode supporting evidence for event {}/{}", row["run_id"], row["event_id"]
                    )

            config_dict: dict[str, Any] = {}
            if row["config_json"]:
                try:
                    config_dict = json.loads(row["config_json"])
                except json.JSONDecodeError:
                    logger.warning("Failed to decode correlation run config for run {}", row["run_id"])  # noqa: TRY400

            event_key = (row["run_id"], row["event_id"])
            metrics = tuple(metrics_map.get(event_key, []))

            records.append(
                CorrelationEventRecord(
                    run_id=row["run_id"],
                    event_id=row["event_id"],
                    source=row["source"],
                    title=row["title"],
                    start=_to_datetime(row["start"]),
                    end=_to_datetime(row["end"]),
                    categories=tuple(categories),
                    metadata=metadata,
                    supporting_evidence=supporting_evidence,
                    metrics=metrics,
                    run_started_at=_to_datetime(row["started_at"]),
                    run_completed_at=_to_datetime(row["completed_at"]),
                    run_window_days=int(row["window_days"]),
                    run_config=config_dict,
                )
            )

        return records

    def _get_connection(self) -> sqlite3.Connection:
        """Create and return a new database connection.

        Note: Each call creates a new connection. Use with 'with' statement for proper cleanup.
        """
        db_file = self.out_dir / "bot.db"
        return sqlite3.connect(db_file.as_posix())


def _to_datetime(value: Optional[str]) -> datetime:
    """Parse an ISO format timestamp string to datetime.

    Args:
        value: ISO format timestamp string (may be None from SQL NULL values)

    Returns:
        Parsed datetime object

    Raises:
        ValueError: If value is None or invalid ISO format
    """
    if value is None:
        raise ValueError("Expected ISO timestamp but received None")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - defensive
        logger.error("Failed to parse ISO timestamp '{}': {}", value, exc)
        raise
