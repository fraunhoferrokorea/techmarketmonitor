"""Re-summarize stored article(s) for a date and regenerate the daily markdown report."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import date, datetime, timezone

import httpx

from src.config import load_settings
from src.daily_report import save_daily_report
from src.models import FilteredArticle
from src.summarizer import Summarizer


def _html_to_text(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_summary(url: str, fallback: str) -> str:
    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=30.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TechMarketMonitor/1.0)"},
    )
    resp.raise_for_status()
    text = _html_to_text(resp.text)
    return text[:4000] if text else fallback


def regen_daily_report(log_date: date) -> None:
    settings = load_settings()
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM daily_logs WHERE log_date = ? ORDER BY id ASC",
        (log_date.isoformat(),),
    ).fetchall()
    conn.close()

    if not rows:
        raise SystemExit(f"No articles stored for {log_date.isoformat()}")

    summarizer = Summarizer(settings)
    summarized = []

    for row in rows:
        print(f"Re-summarizing: {row['title']}")
        try:
            content = _fetch_summary(row["url"], row["llm_summary"])
        except Exception as exc:
            print(f"  Fetch failed ({exc}) — using stored llm_summary as fallback")
            content = row["llm_summary"]

        published_at = None
        if row["published_at"]:
            published_at = datetime.fromisoformat(row["published_at"])
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)

        article = FilteredArticle(
            title=row["title"],
            url=row["url"],
            summary=content,
            source_name=row["source_name"],
            category=row["category"],
            published_at=published_at,
            matched_keywords=json.loads(row["matched_keywords"]),
        )
        summarized.append(summarizer.summarize(article))

    path = save_daily_report(log_date, summarized, top_keywords=settings.keywords[:3])
    print(f"Saved → {path}")
    if summarized:
        print("\n--- keyword_relevance preview ---")
        print(summarized[0].keyword_relevance)


if __name__ == "__main__":
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 6, 21)
    regen_daily_report(target)
