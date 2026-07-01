"""Purge foreign/non-domestic articles from DB and rebuild daily markdown."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_settings
from src.daily_sync import rebuild_markdown_from_db
from src.storage import DailyLogStore


def main() -> None:
    settings = load_settings()
    store = DailyLogStore(settings.database_path)
    purged = store.purge_non_domestic_entries()
    print(f"Purged {purged} non-domestic row(s) from {settings.database_path}")

    dates = store.get_log_dates()
    if not dates:
        print("No log dates left in DB.")
        return

    for d in dates:
        result = rebuild_markdown_from_db(d, store, settings)
        print(f"[{result['status']}] {d.isoformat()} ({result.get('stored', '?')} entries)")


if __name__ == "__main__":
    main()
