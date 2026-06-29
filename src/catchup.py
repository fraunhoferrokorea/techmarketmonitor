from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from src.config import Settings, load_settings
from src.daily_sync import repair_inconsistencies
from src.daily_windows import now_kst, window_end_for_log_date
from src.pipeline import run_daily_monitor
from src.storage import DailyLogStore
from src.scheduler_state import (
    load_last_completed_log_date,
    report_exists,
    save_last_completed_log_date,
)

logger = logging.getLogger(__name__)


def owed_log_dates(now: datetime | None = None) -> list[date]:
    """Return report dates still missing through today (inclusive), oldest first."""
    current = now or now_kst()
    today = current.date()
    last_completed = load_last_completed_log_date()

    if last_completed is None:
        return [today - timedelta(days=1)]

    if last_completed >= today:
        return []

    dates: list[date] = []
    cursor = last_completed + timedelta(days=1)
    while cursor <= today:
        dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def run_daily_catchup(
    settings: Settings | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Run the daily pipeline for every missing report through today."""
    settings = settings or load_settings()
    current = now or now_kst()
    store = DailyLogStore(settings.database_path)
    results: list[dict] = []

    repair_results = repair_inconsistencies(settings=settings, now=current)
    for item in repair_results:
        item["phase"] = "repair"
        results.append(item)

    for log_date in owed_log_dates(current):
        window_end = window_end_for_log_date(log_date, current)

        if report_exists(log_date) and store.count_for_date(log_date) > 0:
            logger.info(
                "Report and DB entries already exist for %s — marking complete",
                log_date,
            )
            save_last_completed_log_date(log_date)
            results.append(
                {
                    "log_date": log_date.isoformat(),
                    "status": "skipped_existing_report",
                }
            )
            continue

        if report_exists(log_date):
            logger.warning(
                "Report file exists for %s but DB has no entries — re-running pipeline",
                log_date,
            )

        logger.info(
            "Catch-up run for report %s (window ends %s KST)",
            log_date,
            window_end.isoformat(),
        )
        result = run_daily_monitor(
            log_date=log_date,
            settings=settings,
            window_end=window_end,
        )
        result["log_date"] = log_date.isoformat()
        result["status"] = "ran"
        results.append(result)
        save_last_completed_log_date(log_date)

    if not results:
        logger.info("No missing daily reports to process")

    return results
