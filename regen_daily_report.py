"""Re-summarize stored article(s) for a date and regenerate the daily markdown report."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from openai import APIStatusError, BadRequestError, RateLimitError

from src.config import load_settings
from src.daily_sync import rebuild_markdown_from_db
from src.models import FilteredArticle
from src.storage import DailyLogStore
from src.summarizer import Summarizer

_TPD_WAIT_RE = re.compile(r"try again in (\d+)m([\d.]+)s", re.I)
_SUMMARY_CHAR_LIMIT = 2000


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


def _progress_path(log_date: date) -> Path:
    return Path("output") / f".regen_progress_{log_date.isoformat()}.json"


def _load_progress(log_date: date) -> set[int]:
    path = _progress_path(log_date)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {int(x) for x in data.get("completed_ids", [])}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return set()


def _save_progress(log_date: date, completed_ids: set[int]) -> None:
    path = _progress_path(log_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"completed_ids": sorted(completed_ids)}, indent=2),
        encoding="utf-8",
    )


def _safe_print(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(message.encode(encoding, errors="replace").decode(encoding))


def _has_rd_format(ko_summary_steps_raw: str) -> bool:
    try:
        steps = json.loads(ko_summary_steps_raw or "[]")
    except json.JSONDecodeError:
        return False
    return any("투자 주체" in step for step in steps)


def _truncate_summary(text: str, limit: int = _SUMMARY_CHAR_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0]


def _wait_for_tpd_limit(exc: RateLimitError) -> None:
    msg = str(exc)
    match = _TPD_WAIT_RE.search(msg)
    if match:
        wait = int(match.group(1)) * 60 + float(match.group(2)) + 10
    else:
        wait = 120.0
    print(f"  Groq TPD limit - waiting {wait:.0f}s before retry...")
    time.sleep(wait)


def _summarize_with_tpd_retry(
    summarizer: Summarizer,
    article: FilteredArticle,
    *,
    summary_limit: int = _SUMMARY_CHAR_LIMIT,
):
    from dataclasses import replace

    json_retries = 0
    size_retries = 0
    current_limit = summary_limit
    while True:
        attempt_article = replace(
            article,
            summary=_truncate_summary(article.summary, current_limit),
        )
        try:
            return summarizer.summarize(attempt_article)
        except RateLimitError as exc:
            if "tokens per day" in str(exc).lower() or "tpd" in str(exc).lower():
                _wait_for_tpd_limit(exc)
                continue
            raise
        except BadRequestError as exc:
            if "json_validate_failed" in str(exc) and json_retries < 2:
                json_retries += 1
                _safe_print(f"  JSON validation failed - retry {json_retries}/2...")
                time.sleep(2.0)
                continue
            raise
        except APIStatusError as exc:
            if exc.status_code == 413 and size_retries < 2:
                size_retries += 1
                current_limit = max(800, current_limit // 2)
                _safe_print(f"  Request too large - retry with {current_limit} chars...")
                time.sleep(2.0)
                continue
            raise


def regen_daily_report(
    log_date: date,
    *,
    fetch_urls: bool = False,
    resume: bool = True,
) -> None:
    settings = load_settings()
    store = DailyLogStore(settings.database_path)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM daily_logs WHERE log_date = ? ORDER BY id ASC",
        (log_date.isoformat(),),
    ).fetchall()
    conn.close()

    if not rows:
        raise SystemExit(f"No articles stored for {log_date.isoformat()}")

    completed = _load_progress(log_date) if resume else set()
    if completed:
        print(f"Resuming: {len(completed)}/{len(rows)} already done")

    summarizer = Summarizer(settings)

    for i, row in enumerate(rows, 1):
        row_id = int(row["id"])
        if row_id in completed:
            continue
        if _has_rd_format(row["ko_summary_steps"]):
            _safe_print(f"[{i}/{len(rows)}] Skip (already updated): {row['title']}")
            continue

        _safe_print(f"[{i}/{len(rows)}] Re-summarizing: {row['title']}")
        if fetch_urls:
            try:
                content = _fetch_summary(row["url"], row["llm_summary"])
            except Exception as exc:
                print(f"  Fetch failed ({exc}) - using stored llm_summary")
                content = row["llm_summary"]
        else:
            content = row["llm_summary"]
        content = _truncate_summary(content)

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
        try:
            summary = _summarize_with_tpd_retry(summarizer, article)
        except Exception as exc:
            _safe_print(f"  Failed ({type(exc).__name__}): {exc}")
            continue
        store.update_summarized_entry(row_id, summary)
        completed.add(row_id)
        _save_progress(log_date, completed)

        result = rebuild_markdown_from_db(
            log_date, store, settings, repolish_db=False, include_foreign=True
        )
        print(f"  Saved DB + markdown ({result.get('daily_report')})")
        time.sleep(1.5)

    _progress_path(log_date).unlink(missing_ok=True)
    print(f"Done: {log_date.isoformat()} ({len(rows)} articles)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a.startswith("-") is False]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    target = date.fromisoformat(args[0]) if args else date(2026, 6, 21)
    regen_daily_report(
        target,
        fetch_urls="--fetch" in flags,
        resume="--no-resume" not in flags,
    )
