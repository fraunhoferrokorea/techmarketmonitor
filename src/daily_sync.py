"""Repair and reprocess daily logs so DB, markdown, and pipeline rules stay aligned."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.config import Settings, load_settings
from src.daily_windows import window_end_for_log_date
from src.daily_report import save_daily_report
from src.korea_scope import is_domestic_news
from src.models import SummarizedArticle
from src.summarizer import repolish_summarized_article
from src.pipeline import run_daily_monitor
from src.scheduler_state import (
    load_last_completed_log_date,
    report_exists,
    remove_report,
    report_dates_from_disk,
    save_last_completed_log_date,
)
from src.storage import DailyLogStore

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


def _row_to_article(row: dict) -> SummarizedArticle:
    published_at = None
    raw_pub = row.get("published_at")
    if raw_pub:
        try:
            published_at = datetime.fromisoformat(raw_pub)
            if published_at.tzinfo is None:
                from datetime import timezone

                published_at = published_at.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return SummarizedArticle(
        title=row["title"],
        url=row["url"],
        source_name=row["source_name"],
        category=row["category"],
        published_at=published_at,
        matched_keywords=row["matched_keywords"],
        llm_summary=row["llm_summary"] or "",
        key_trends=row["key_trends"],
        ko_summary_steps=row["ko_summary_steps"],
        en_summary_steps=row["en_summary_steps"],
        keyword_relevance=row.get("keyword_relevance") or "",
        ko_one_liner=row.get("ko_one_liner") or "",
        rd_match_score=int(row.get("rd_match_score") or 0),
        rd_proposable_area=row.get("rd_proposable_area") or "",
        rd_fact_basis=row.get("rd_fact_basis") or "",
    )


def scan_inconsistencies(store: DailyLogStore) -> list[dict]:
    """Find dates where markdown files and DB rows are out of sync."""
    tracked_dates = set(store.get_log_dates()) | set(report_dates_from_disk())
    issues: list[dict] = []

    for log_date in sorted(tracked_dates):
        has_md = report_exists(log_date)
        db_count = store.count_for_date(log_date)
        if has_md and db_count == 0:
            issues.append(
                {
                    "log_date": log_date.isoformat(),
                    "issue": "md_without_db",
                    "message": "markdown exists but DB has no entries",
                }
            )
        elif not has_md and db_count > 0:
            issues.append(
                {
                    "log_date": log_date.isoformat(),
                    "issue": "db_without_md",
                    "message": "DB has entries but markdown is missing",
                }
            )

    return issues


def realign_log_dates_from_published_at(store: DailyLogStore) -> dict:
    """Move DB rows to the KST calendar day of published_at (catch-up rule).

    Rows whose URL already exists on the target date are removed as duplicates.
    """
    moved = 0
    deleted = 0
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT id, log_date, url, published_at FROM daily_logs ORDER BY id ASC"
        ).fetchall()
        for row in rows:
            raw_pub = row["published_at"]
            if not raw_pub:
                continue
            try:
                published_at = datetime.fromisoformat(raw_pub)
            except ValueError:
                continue
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            pub_date = published_at.astimezone(KST).date().isoformat()
            if pub_date == row["log_date"]:
                continue

            existing = conn.execute(
                "SELECT id FROM daily_logs WHERE url = ? AND log_date = ?",
                (row["url"], pub_date),
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM daily_logs WHERE id = ?", (row["id"],))
                deleted += 1
            else:
                conn.execute(
                    "UPDATE daily_logs SET log_date = ? WHERE id = ?",
                    (pub_date, row["id"]),
                )
                moved += 1

    return {"moved": moved, "deleted": deleted}


def refresh_all_daily_markdown(
    store: DailyLogStore,
    settings: Settings,
) -> list[dict]:
    """Rebuild markdown for every DB date and remove stale report files."""
    db_dates = set(store.get_log_dates())
    results: list[dict] = []

    for log_date in sorted(db_dates):
        results.append(rebuild_markdown_from_db(log_date, store, settings))

    for log_date in sorted(set(report_dates_from_disk()) - db_dates):
        removed = remove_report(log_date)
        results.append(
            {
                "log_date": log_date.isoformat(),
                "status": "removed_stale_markdown",
                "removed_markdown": removed,
            }
        )

    return results


def clear_daily(log_date: date, store: DailyLogStore) -> dict:
    """Remove DB rows and markdown for one log date."""
    deleted = store.delete_for_date(log_date)
    removed_md = remove_report(log_date)
    return {
        "log_date": log_date.isoformat(),
        "deleted_db_rows": deleted,
        "removed_markdown": removed_md,
    }


def rebuild_markdown_from_db(
    log_date: date,
    store: DailyLogStore,
    settings: Settings,
    *,
    repolish_db: bool = True,
) -> dict:
    """Regenerate markdown from stored summaries (no LLM)."""
    rows = store.get_entries_for_date(log_date)
    if not rows:
        return {
            "log_date": log_date.isoformat(),
            "status": "skipped_no_db_entries",
        }

    articles: list[SummarizedArticle] = []
    repolished_rows = 0
    skipped_foreign = 0
    for row in rows:
        article = repolish_summarized_article(_row_to_article(row))
        if not is_domestic_news(article):
            skipped_foreign += 1
            continue
        articles.append(article)
        if repolish_db:
            original_ko = row.get("ko_summary_steps") or []
            original_kr = row.get("keyword_relevance") or ""
            if (
                article.ko_summary_steps != original_ko
                or article.keyword_relevance != original_kr
            ):
                store.update_korean_text(
                    row["id"],
                    article.ko_summary_steps,
                    article.keyword_relevance,
                )
                repolished_rows += 1

    if not articles:
        return {
            "log_date": log_date.isoformat(),
            "status": "skipped_no_domestic_entries",
            "skipped_foreign": skipped_foreign,
        }

    path = save_daily_report(
        log_date,
        articles,
        top_keywords=settings.keywords[:3],
    )
    return {
        "log_date": log_date.isoformat(),
        "status": "rebuilt_markdown",
        "stored": len(articles),
        "skipped_foreign": skipped_foreign,
        "repolished_rows": repolished_rows,
        "daily_report": str(path) if path else None,
    }


def reprocess_date(
    log_date: date,
    settings: Settings,
    store: DailyLogStore,
    now: datetime,
) -> dict:
    """Clear one date and rerun fetch → filter → summarize with current pipeline rules."""
    cleared = clear_daily(log_date, store)
    window_end = window_end_for_log_date(log_date, now)
    logger.info(
        "Reprocessing %s (window ends %s)",
        log_date.isoformat(),
        window_end.isoformat(),
    )
    result = run_daily_monitor(
        log_date=log_date,
        settings=settings,
        window_end=window_end,
    )
    result["status"] = "reprocessed"
    result["cleared"] = cleared
    return result


def repair_inconsistencies(
    settings: Settings | None = None,
    now: datetime | None = None,
    *,
    reprocess_lookback_days: int = 7,
) -> list[dict]:
    """Fix md/DB mismatches using the cheapest path for each issue type.

    Markdown-without-DB dates older than the lookback window are skipped
  (use ``daily-reprocess --from … --to …`` to rebuild history intentionally).
    """
    settings = settings or load_settings()
    current = now or datetime.now(tz=KST)
    store = DailyLogStore(settings.database_path)
    results: list[dict] = []
    today = current.date()
    reprocess_cutoff = today - timedelta(days=reprocess_lookback_days)
    last_completed = load_last_completed_log_date()

    for issue in scan_inconsistencies(store):
        log_date = date.fromisoformat(issue["log_date"])
        if issue["issue"] == "db_without_md":
            result = rebuild_markdown_from_db(log_date, store, settings)
        elif last_completed is not None and log_date <= last_completed:
            result = {
                "log_date": log_date.isoformat(),
                "status": "skipped_legacy_md_without_db",
                "message": (
                    "markdown without DB but date is on or before last_completed_log_date; "
                    "run daily-reprocess to rebuild intentionally"
                ),
            }
        elif log_date < reprocess_cutoff:
            result = {
                "log_date": log_date.isoformat(),
                "status": "skipped_historical_md_without_db",
                "message": (
                    f"markdown without DB older than {reprocess_lookback_days} days; "
                    "run daily-reprocess to rebuild intentionally"
                ),
            }
        else:
            result = reprocess_date(log_date, settings, store, current)
        result["issue"] = issue["issue"]
        results.append(result)

    repaired_dates = [
        date.fromisoformat(r["log_date"])
        for r in results
        if r.get("status") in ("reprocessed", "rebuilt_markdown")
    ]
    if repaired_dates:
        latest = max(repaired_dates)
        if last_completed is None or latest > last_completed:
            save_last_completed_log_date(latest)

    return results


def reprocess_range(
    start_date: date,
    end_date: date,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Re-run the daily pipeline for each date in [start_date, end_date] (inclusive)."""
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    settings = settings or load_settings()
    current = now or datetime.now(tz=KST)
    store = DailyLogStore(settings.database_path)
    results: list[dict] = []

    cursor = start_date
    while cursor <= end_date:
        results.append(reprocess_date(cursor, settings, store, current))
        cursor += timedelta(days=1)

    save_last_completed_log_date(end_date)
    return results
