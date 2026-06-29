"""Rebuild daily markdown reports from stored DB data — no LLM calls.

Usage:
    python rebuild_daily_markdown.py            # rebuilds all dates in DB
    python rebuild_daily_markdown.py 2026-06-23 # rebuilds one specific date
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_settings
from src.daily_sync import rebuild_markdown_from_db
from src.storage import DailyLogStore


def main() -> None:
    settings = load_settings()
    store = DailyLogStore(settings.database_path)

    if len(sys.argv) > 1:
        dates = [date.fromisoformat(sys.argv[1])]
    else:
        dates = store.get_log_dates()

    if not dates:
        print("No data found in database.")
        return

    print(f"Rebuilding {len(dates)} date(s): {[d.isoformat() for d in dates]}")
    for d in dates:
        result = rebuild_markdown_from_db(d, store, settings)
        print(f"[{result['status']}] {d.isoformat()}")


if __name__ == "__main__":
    main()
