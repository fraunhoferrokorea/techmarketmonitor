"""
Run the monthly Word report only if today is the last business day of the month.
Registered as a daily Task Scheduler job — no-ops on most days.

GitHub Actions passes --check-only: exit 1 when today is NOT the last business day
(so the workflow skips the monthly step without failing the job).
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date


def last_business_day_of_month(year: int, month: int) -> date:
    """Return the last Monday–Friday of the given month."""
    last_day = calendar.monthrange(year, month)[1]
    candidate = date(year, month, last_day)
    while candidate.weekday() >= 5:  # 5=Sat, 6=Sun
        candidate = date(candidate.year, candidate.month, candidate.day - 1)
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Exit 1 when today is not the last business day (for GitHub Actions gating).",
    )
    args = parser.parse_args()

    today = date.today()
    lbd = last_business_day_of_month(today.year, today.month)

    if today != lbd:
        print(f"[monthly-check] Today ({today}) is not the last business day ({lbd}). Skipping.")
        sys.exit(1 if args.check_only else 0)

    if args.check_only:
        print(f"[monthly-check] Today IS the last business day ({lbd}). Running monthly report.")
        return

    print(f"[monthly-check] Today IS the last business day ({lbd}). Running monthly report…")

    # Import here so the script can be tested without the full venv on PATH
    import logging

    from src.config import load_settings
    from src.monthly import run_monthly_report

    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    result = run_monthly_report(year=today.year, month=today.month, cleanup_daily=True)
    print(f"[monthly-check] Done: {result}")


if __name__ == "__main__":
    main()
