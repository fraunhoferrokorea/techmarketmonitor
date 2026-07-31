"""
Run the monthly Markdown report only if today is the last business day of the month.
Registered as a daily Task Scheduler job — no-ops on most days.

GitHub Actions passes --check-only: exit 1 when today is NOT the last business day
(so the workflow skips the monthly step without failing the job).
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date, timedelta


def last_business_day_of_month(year: int, month: int) -> date:
    """Return the last Monday–Friday of the given month."""
    last_day = calendar.monthrange(year, month)[1]
    candidate = date(year, month, last_day)
    while candidate.weekday() >= 5:  # 5=Sat, 6=Sun
        candidate = date(candidate.year, candidate.month, candidate.day - 1)
    return candidate


def _today_kst() -> date:
    try:
        from src.daily_windows import now_kst

        return now_kst().date()
    except Exception:
        return date.today()


def _yesterday_daily_ready(today: date) -> tuple[bool, str]:
    """Require yesterday's daily before LBD monthly (avoid StartWhenAvailable races)."""
    from src.scheduler_state import load_last_completed_log_date, report_exists

    yesterday = today - timedelta(days=1)
    last_completed = load_last_completed_log_date()
    if report_exists(yesterday) or (
        last_completed is not None and last_completed >= yesterday
    ):
        return True, yesterday.isoformat()
    return False, yesterday.isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Exit 1 when today is not the last business day (for GitHub Actions gating).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if monthly_YYYY-MM.md already exists.",
    )
    args = parser.parse_args()

    today = _today_kst()
    lbd = last_business_day_of_month(today.year, today.month)

    if today != lbd:
        print(f"[monthly-check] Today ({today}) is not the last business day ({lbd}). Skipping.")
        sys.exit(1 if args.check_only else 0)

    ready, yesterday = _yesterday_daily_ready(today)
    if not ready:
        print(
            f"[monthly-check] Last business day ({lbd}), but daily for {yesterday} "
            "is not ready yet. Run daily-catchup first; skipping monthly."
        )
        sys.exit(1 if args.check_only else 0)

    from src.job_guard import monthly_report_path

    report_path = monthly_report_path(today.year, today.month)
    if report_path.is_file() and not args.force:
        print(f"[monthly-check] Already exists: {report_path}. Skipping.")
        # check-only exit 1 → GHA treats as "nothing to run" (same as non-LBD).
        sys.exit(1 if args.check_only else 0)

    if args.check_only:
        print(f"[monthly-check] Today IS the last business day ({lbd}). Running monthly report.")
        return

    print(f"[monthly-check] Today IS the last business day ({lbd}). Running monthly report…")

    import logging

    from src.job_guard import pipeline_lock
    from src.monthly import run_monthly_report

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    with pipeline_lock("pipeline") as acquired:
        if not acquired:
            print("[monthly-check] Another pipeline job is running — skip (will retry later).")
            sys.exit(0)

        if report_path.is_file() and not args.force:
            print(f"[monthly-check] Already exists: {report_path}. Skipping.")
            return

        # Keep dailies until cloud/pages sync is confirmed (GHA already uses --no-cleanup).
        result = run_monthly_report(
            year=today.year,
            month=today.month,
            cleanup_daily=False,
        )
        print(f"[monthly-check] Done: {result}")


if __name__ == "__main__":
    main()
