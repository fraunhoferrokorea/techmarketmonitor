"""Re-summarize one DB row by id and rebuild daily markdown."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

from src.config import load_settings
from src.daily_sync import rebuild_markdown_from_db
from src.models import FilteredArticle
from src.storage import DailyLogStore
from src.summarizer import Summarizer


def main() -> None:
    row_id = int(sys.argv[1])
    settings = load_settings()
    store = DailyLogStore(settings.database_path)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM daily_logs WHERE id = ?", (row_id,)).fetchone()
    conn.close()
    if not row:
        raise SystemExit(f"No row id={row_id}")

    published_at = None
    if row["published_at"]:
        published_at = datetime.fromisoformat(row["published_at"])
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

    article = FilteredArticle(
        title=row["title"],
        url=row["url"],
        summary=row["llm_summary"],
        source_name=row["source_name"],
        category=row["category"],
        published_at=published_at,
        matched_keywords=json.loads(row["matched_keywords"]),
    )
    summary = Summarizer(settings).summarize(article)
    store.update_summarized_entry(row_id, summary)
    log_date = datetime.fromisoformat(row["log_date"]).date()
    result = rebuild_markdown_from_db(log_date, store, settings, repolish_db=False)
    print("one-liner:", summary.ko_one_liner)
    for i, step in enumerate(summary.ko_summary_steps[:3], 1):
        print(f"ko[{i}]:", step)
    print("markdown:", result.get("daily_report"))


if __name__ == "__main__":
    main()
