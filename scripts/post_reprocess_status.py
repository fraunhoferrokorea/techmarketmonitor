"""Print DB/markdown/scheduler status after a reprocess run."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_settings
from src.daily_sync import scan_inconsistencies
from src.scheduler_state import load_last_completed_log_date, report_dates_from_disk
from src.storage import DailyLogStore


def main() -> None:
    settings = load_settings()
    store = DailyLogStore(settings.database_path)
    conn = sqlite3.connect(settings.database_path)
    rows = conn.execute(
        "SELECT log_date, COUNT(*) FROM daily_logs GROUP BY log_date ORDER BY log_date"
    ).fetchall()
    conn.close()

    print("=== POST-RUN STATUS ===")
    print("last_completed:", load_last_completed_log_date())
    print("DB rows by date:", rows)
    print(
        "disk dates:",
        sorted(d.isoformat() for d in report_dates_from_disk()),
    )
    print("inconsistencies:", scan_inconsistencies(store))


if __name__ == "__main__":
    main()
