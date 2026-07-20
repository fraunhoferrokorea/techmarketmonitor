from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from src.config import Settings, load_settings
from src.daily_report import save_empty_daily_report
from src.daily_sync import repair_inconsistencies
from src.daily_windows import now_kst, window_end_for_log_date
from src.pipeline import run_daily_monitor
from src.storage import DailyLogStore
from src.scheduler_state import (
    load_last_completed_log_date,
    report_dates_from_disk,
    report_exists,
    save_last_completed_log_date,
)

logger = logging.getLogger(__name__)


def _date_has_content(log_date: date, store: DailyLogStore) -> bool:
    """True when the date already has markdown or DB rows.

    Existing markdown (including empty stubs and legacy md-without-db) counts as
    present so catch-up does not delete recoverable reports by re-fetching.
    """
    if report_exists(log_date):
        return True
    return store.count_for_date(log_date) > 0


def owed_log_dates(
    now: datetime | None = None,
    store: DailyLogStore | None = None,
) -> list[date]:
    """Return report dates still missing through yesterday (inclusive), oldest first.

    Includes calendar holes (no markdown / no DB) even when
    ``last_completed_log_date`` has already advanced past them.
    Never includes *today* — the 08:00 KST catch-up would otherwise finalize
    a partial midnight–08:00 window and never retry the rest of the day.
    """
    current = now or now_kst()
    today = current.date()
    latest_owed = today - timedelta(days=1)
    last_completed = load_last_completed_log_date()

    if latest_owed < date(1970, 1, 1):
        return []

    present: set[date] = set(report_dates_from_disk())
    if store is not None:
        present |= set(store.get_log_dates())

    if last_completed is None and not present:
        return [latest_owed]

    start_candidates: list[date] = []
    if last_completed is not None:
        start_candidates.append(last_completed + timedelta(days=1))
    if present:
        start_candidates.append(min(present))
    start = min(start_candidates) if start_candidates else latest_owed

    if start > latest_owed:
        return []

    dates: list[date] = []
    cursor = start
    while cursor <= latest_owed:
        if store is None:
            if not report_exists(cursor):
                dates.append(cursor)
        elif not _date_has_content(cursor, store):
            dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def run_daily_catchup(
    settings: Settings | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Run the daily pipeline for every missing report through yesterday."""
    settings = settings or load_settings()
    current = now or now_kst()
    store = DailyLogStore(settings.database_path)
    results: list[dict] = []

    repair_results = repair_inconsistencies(settings=settings, now=current)
    for item in repair_results:
        item["phase"] = "repair"
        results.append(item)

    for log_date in owed_log_dates(current, store=store):
        window_end = window_end_for_log_date(log_date, current)

        if _date_has_content(log_date, store):
            logger.info(
                "Report already present for %s — marking complete",
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

        stored = int(result.get("stored") or 0)
        if stored > 0 and report_exists(log_date):
            result["status"] = "ran"
            save_last_completed_log_date(log_date)
        elif log_date < current.date():
            # Past calendar day with a closed window: keep a visible placeholder
            # so the date is not silently skipped forever.
            stub = save_empty_daily_report(
                log_date,
                top_keywords=settings.analysis_keywords,
            )
            result["status"] = "ran_empty"
            result["daily_report"] = str(stub)
            save_last_completed_log_date(log_date)
            logger.info(
                "No articles for %s — wrote empty placeholder and marked complete",
                log_date,
            )
        else:
            result["status"] = "ran_incomplete"
            logger.warning(
                "Catch-up for %s produced no articles — not marking complete",
                log_date,
            )

        results.append(result)

    # Advance cursor through already-complete days after the last hole we filled.
    yesterday = current.date() - timedelta(days=1)
    last = load_last_completed_log_date()
    if last is not None and last < yesterday:
        cursor = last + timedelta(days=1)
        while cursor <= yesterday and _date_has_content(cursor, store):
            save_last_completed_log_date(cursor)
            cursor += timedelta(days=1)

    if not results:
        logger.info("No missing daily reports to process")

    return results
