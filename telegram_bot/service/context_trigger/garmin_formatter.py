from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from telegram_bot.service.influxdb_garmin_data_exporter import GarminExportData


def format_garmin_data_for_context(garmin_export: GarminExportData, tz: ZoneInfo) -> Optional[str]:  # noqa: C901
    """Format Garmin export data into readable context for LLM prompt.

    This is extracted from the original ContextTriggerService._format_garmin_data_for_context
    and adapted to use the provided timezone.
    """
    if not garmin_export:
        return None

    context_parts: list[str] = []

    def _last_timestamp_dt(df) -> Optional[datetime]:
        if df is None:
            return None
        try:
            cols = list(df.columns)
        except Exception:
            return None
        candidates = [c for c in cols if any(tok in c.lower() for tok in ["time", "date"])]
        for col in candidates:
            try:
                series = pd.to_datetime(df[col], errors="coerce")
                series = series.dropna()
                if not series.empty:
                    ts = series.iloc[-1]
                    # Ensure tz-aware
                    if getattr(ts, "tzinfo", None) is None:
                        try:
                            ts = ts.tz_localize(tz)
                        except Exception:
                            pass
                    return ts
            except Exception:
                continue
        return None

    def _is_stale(ts: Optional[datetime], hours: int = 6) -> Optional[bool]:
        if not ts:
            return None
        try:
            now = datetime.now(tz=tz)
            return (now - ts).total_seconds() > hours * 3600
        except Exception:
            return None

    # Sleep data
    if garmin_export.sleep_summary is not None and not garmin_export.sleep_summary.empty:
        latest_sleep = garmin_export.sleep_summary.iloc[-1]
        sleep_score = latest_sleep.get("sleepScore", 0)
        sleep_hours = latest_sleep.get("sleepTimeSeconds", 0) / 3600
        context_parts.append(f"Latest Sleep: Score {sleep_score}/100, Duration {sleep_hours:.1f}h")

    # Body Battery current state
    if garmin_export.body_battery_intraday is not None and not garmin_export.body_battery_intraday.empty:
        current_bb = garmin_export.body_battery_intraday.iloc[-1].get("BodyBatteryLevel")
        bb_line = f"Current Body Battery: {current_bb}%" if current_bb is not None else "Current Body Battery: n/a"
        last_ts_dt = _last_timestamp_dt(garmin_export.body_battery_intraday)
        stale = _is_stale(last_ts_dt, hours=6)
        freshness = "STALE" if stale else "fresh" if stale is not None else "unknown"
        if last_ts_dt:
            bb_line += f" (last sample: {last_ts_dt.strftime('%Y-%m-%d %H:%M %Z')}, {freshness})"
        context_parts.append(bb_line)

    # Daily stats (steps, stress)
    if garmin_export.daily_stats is not None and not garmin_export.daily_stats.empty:
        latest_day = garmin_export.daily_stats.iloc[-1]
        steps = latest_day.get("totalSteps", 0)
        stress_pct = latest_day.get("stressPercentage", 0)
        context_parts.append(f"Today: {steps:,} steps, {stress_pct:.1f}% stress")

    # Stress/HR freshness lines (if available)
    if garmin_export.stress_intraday is not None and not garmin_export.stress_intraday.empty:
        last_ts_dt = _last_timestamp_dt(garmin_export.stress_intraday)
        stale = _is_stale(last_ts_dt, hours=6)
        freshness = "STALE" if stale else "fresh" if stale is not None else "unknown"
        if last_ts_dt:
            context_parts.append(f"Stress data last sample: {last_ts_dt.strftime('%Y-%m-%d %H:%M %Z')} ({freshness})")
    if garmin_export.heart_rate_intraday is not None and not garmin_export.heart_rate_intraday.empty:
        last_ts_dt = _last_timestamp_dt(garmin_export.heart_rate_intraday)
        stale = _is_stale(last_ts_dt, hours=6)
        freshness = "STALE" if stale else "fresh" if stale is not None else "unknown"
        if last_ts_dt:
            context_parts.append(
                f"Heart rate data last sample: {last_ts_dt.strftime('%Y-%m-%d %H:%M %Z')} ({freshness})"
            )

    return "\n".join(context_parts) if context_parts else None


def _getattr_or(item, name: str, default=None):
    """Safe attribute or dict access helper for flexible inputs."""
    if hasattr(item, name):
        return getattr(item, name)
    if isinstance(item, dict):
        return item.get(name, default)
    return default


def format_current_sleep_status_md(garmin_summary, tz: ZoneInfo) -> str:
    """Format current sleep and body battery status in markdown.

    Accepts either an object with attributes or a dict-like with keys:
    - sleep_time_s, deep_s, light_s, rem_s, restless_cnt, sleep_score,
      avg_overnight_hrv (optional), bb_current, bb_delta_sleep
    """
    sleep_time_s = int(_getattr_or(garmin_summary, "sleep_time_s", 0) or 0)
    deep_s = int(_getattr_or(garmin_summary, "deep_s", 0) or 0)
    light_s = int(_getattr_or(garmin_summary, "light_s", 0) or 0)
    rem_s = int(_getattr_or(garmin_summary, "rem_s", 0) or 0)
    restless_cnt = int(_getattr_or(garmin_summary, "restless_cnt", 0) or 0)
    sleep_score = int(_getattr_or(garmin_summary, "sleep_score", 0) or 0)
    avg_overnight_hrv = _getattr_or(garmin_summary, "avg_overnight_hrv", None)
    bb_current = int(_getattr_or(garmin_summary, "bb_current", 0) or 0)
    bb_delta_sleep = int(_getattr_or(garmin_summary, "bb_delta_sleep", 0) or 0)

    sleep_hours, sleep_minutes = divmod(sleep_time_s // 60, 60)
    deep_hours, deep_minutes = divmod(deep_s // 60, 60)
    light_hours, light_minutes = divmod(light_s // 60, 60)
    rem_hours, rem_minutes = divmod(rem_s // 60, 60)

    status_md = f"""## 🌙 Ostatnia Noc & Aktualny Stan

**Sen (poprzednia noc):**
- 🏆 Sleep Score: **{sleep_score}/100**
- ⏰ Czas snu: **{sleep_hours}h {sleep_minutes}min**
- 🔵 Deep: {deep_hours}h {deep_minutes}min | 🟡 Light: {light_hours}h {light_minutes}min
| 🟢 REM: {rem_hours}h {rem_minutes}min
- 😴 Niespokojne momenty: {restless_cnt}"""

    if avg_overnight_hrv:
        try:
            status_md += f"\n- 💓 Średnie HRV nocne: {float(avg_overnight_hrv):.1f} ms"
        except Exception:
            status_md += f"\n- 💓 Średnie HRV nocne: {avg_overnight_hrv} ms"

    status_md += f"""

**Body Battery:**
- 🔋 Aktualny poziom: **{bb_current}%**
- ⚡ Zmiana podczas snu: {bb_delta_sleep:+d}%"""

    return status_md


def format_garmin_day_markdown_md(day_data, tz: ZoneInfo) -> str:
    """Format daily Garmin data in markdown.

    Expects attributes or keys: date, steps, active_kcal, resting_hr,
    hr_min, hr_avg, hr_max, body_battery(high/avg/low), stress(stress_pct, low_pct, medium_pct, high_pct),
    and optional activities list with keys: name, duration_min, calories, avg_hr, start_time, distance_km.
    """
    date_val = _getattr_or(day_data, "date", None)
    date_str = str(date_val) if date_val is not None else "(unknown)"

    steps = int(_getattr_or(day_data, "steps", 0) or 0)
    active_kcal = int(_getattr_or(day_data, "active_kcal", 0) or 0)
    resting_hr = int(_getattr_or(day_data, "resting_hr", 0) or 0)
    hr_min = int(_getattr_or(day_data, "hr_min", 0) or 0)
    hr_avg = int(_getattr_or(day_data, "hr_avg", 0) or 0)
    hr_max = int(_getattr_or(day_data, "hr_max", 0) or 0)
    stress = _getattr_or(day_data, "stress", {}) or {}
    body_battery = _getattr_or(day_data, "body_battery", {}) or {}

    stress_pct = float(_getattr_or(stress, "stress_pct", 0.0) or 0.0)
    low_pct = float(_getattr_or(stress, "low_pct", 0.0) or 0.0)
    medium_pct = float(_getattr_or(stress, "medium_pct", 0.0) or 0.0)
    high_pct = float(_getattr_or(stress, "high_pct", 0.0) or 0.0)

    bb_high = int(_getattr_or(body_battery, "high", 0) or 0)
    bb_avg = int(_getattr_or(body_battery, "avg", 0) or 0)
    bb_low = int(_getattr_or(body_battery, "low", 0) or 0)

    md = f"""## 📊 Metryki dnia {date_str}

**Podstawowe:**
- 👟 Kroki: **{steps:,}**
- 🔥 Aktywne kalorie: **{active_kcal} kcal**
- 💓 Spoczynkowe HR: **{resting_hr} bpm**

**Tętno (dzień):**
- Min: {hr_min} | Avg: {hr_avg} | Max: {hr_max} bpm

**Body Battery:**
- Max: {bb_high}% | Avg: {bb_avg}% | Min: {bb_low}%

**Stres:**
- Ogólny: {stress_pct:.1f}%
- Niski: {low_pct:.1f}% |
Średni: {medium_pct:.1f}% | Wysoki: {high_pct:.1f}%"""

    activities = _getattr_or(day_data, "activities", []) or []
    if activities:
        md += "\n\n**🏃 Aktywności:**"
        for activity in activities:
            name = _getattr_or(activity, "name", "Unknown") or "Unknown"
            duration_min = int(_getattr_or(activity, "duration_min", 0) or 0)
            calories = int(_getattr_or(activity, "calories", 0) or 0)
            avg_hr = _getattr_or(activity, "avg_hr", None)
            start_time = _getattr_or(activity, "start_time", None)
            distance_km = _getattr_or(activity, "distance_km", None)

            start_time_str = ""
            if start_time:
                try:
                    dt = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
                    start_time_str = dt.astimezone(tz).strftime("%H:%M")
                except Exception:
                    start_time_str = ""

            activity_line = f"\n- **{name}**"
            if start_time_str:
                activity_line += f" ({start_time_str})"
            activity_line += f" - {duration_min}min, {calories} kcal"
            if avg_hr is not None:
                activity_line += f", avg HR: {avg_hr} bpm"
            if distance_km:
                try:
                    d = float(distance_km)
                    if d >= 1:
                        activity_line += f", {d:.1f} km"
                    else:
                        activity_line += f", {d * 1000:.0f} m"
                except Exception:
                    pass
            md += activity_line
    else:
        md += "\n\n**🏃 Aktywności:** Brak zarejestrowanych aktywności"

    return md
