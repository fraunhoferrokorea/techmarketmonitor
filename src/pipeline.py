from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.article_enrichment import enrich_raw_articles
from src.config import Settings, load_settings, load_sources
from src.daily_report import save_daily_report
from src.fetchers.registry import build_fetchers
from src.filter import filter_articles
from src.models import FilteredArticle, RawArticle
from src.policy_priority import gov_target_score
from src.scheduler_state import remove_report, report_exists
from src.storage import DailyLogStore
from src.summarizer import Summarizer

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
_MAX_AGE_HOURS = 24
# Groq free tier: ~100k tokens/day. Each article uses ~2,500 tokens → cap at 30.
# Override with MAX_ARTICLES_PER_RUN env var if needed.
_MAX_ARTICLES_PER_RUN = int(os.getenv("MAX_ARTICLES_PER_RUN", "30"))


def _within_24h(
    articles: list[RawArticle],
    window_end: datetime | None = None,
) -> list[RawArticle]:
    """Keep articles published in the 24 hours ending at window_end.

    Articles with no published_at are kept only for live runs (no window_end).
    """
    if window_end is None:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=_MAX_AGE_HOURS)
        upper = None
    else:
        end = window_end
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        cutoff = end_utc - timedelta(hours=_MAX_AGE_HOURS)
        upper = end_utc

    recent: list[RawArticle] = []
    for article in articles:
        if article.published_at is None:
            if window_end is None:
                recent.append(article)
            continue
        pub = article.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        pub_utc = pub.astimezone(timezone.utc)
        if pub_utc < cutoff:
            logger.debug("Skipping old article (%s): %s", pub.date(), article.title[:60])
            continue
        if upper is not None and pub_utc > upper:
            logger.debug("Skipping future article (%s): %s", pub.date(), article.title[:60])
            continue
        recent.append(article)
    return recent


def _within_log_date(
    articles: list[RawArticle],
    log_date: date,
    window_end: datetime | None = None,
) -> list[RawArticle]:
    """Keep articles published on log_date (KST calendar day).

    Used for catch-up runs so consecutive report dates do not share a rolling
    24h window. Articles without published_at are excluded.
    """
    end_kst: datetime | None = None
    if window_end is not None:
        end = window_end
        if end.tzinfo is None:
            end = end.replace(tzinfo=KST)
        end_kst = end.astimezone(KST)

    matched: list[RawArticle] = []
    for article in articles:
        if article.published_at is None:
            logger.debug("Skipping undated article: %s", article.title[:60])
            continue
        pub = article.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        pub_kst = pub.astimezone(KST)
        if pub_kst.date() != log_date:
            logger.debug(
                "Skipping article outside log_date (%s vs %s): %s",
                pub_kst.date(),
                log_date,
                article.title[:60],
            )
            continue
        if end_kst is not None and pub_kst > end_kst:
            logger.debug("Skipping future article (%s): %s", pub_kst, article.title[:60])
            continue
        matched.append(article)
    return matched


def _article_pipeline_sort_key(article: FilteredArticle) -> tuple[int, int, str]:
    """Policy/S&T plans first, then keyword match count."""
    return (
        -gov_target_score(article),
        -len(article.matched_keywords),
        article.title.lower(),
    )


def _cap_with_policy_priority(
    articles: list[FilteredArticle],
    limit: int,
) -> list[FilteredArticle]:
    """Always keep policy-priority items; fill remaining slots by sort order."""
    if len(articles) <= limit:
        return articles

    ranked = sorted(articles, key=_article_pipeline_sort_key)
    priority = [a for a in ranked if gov_target_score(a) > 0]
    rest = [a for a in ranked if gov_target_score(a) == 0]

    kept = priority[:limit]
    remaining = limit - len(kept)
    if remaining > 0:
        kept.extend(rest[:remaining])
    return sorted(kept, key=_article_pipeline_sort_key)


def run_daily_monitor(
    log_date: date | None = None,
    settings: Settings | None = None,
    window_end: datetime | None = None,
) -> dict:
    settings = settings or load_settings()
    log_date = log_date or date.today()

    keywords = settings.keywords
    if not keywords:
        raise ValueError("No keywords configured — check keywords.txt in project root")

    sources = load_sources()
    fetchers = build_fetchers(sources, keywords)

    raw_articles = []
    for fetcher in fetchers:
        try:
            raw_articles.extend(fetcher.fetch())
        except Exception as exc:
            logger.error("Fetcher failed (%s): %s", fetcher.__class__.__name__, exc)

    if window_end is not None:
        recent_articles = _within_log_date(
            raw_articles, log_date, window_end=window_end
        )
        logger.info(
            "Calendar-day filter (log_date=%s, window_end=%s): %d → %d articles",
            log_date.isoformat(),
            window_end.isoformat(),
            len(raw_articles),
            len(recent_articles),
        )
    else:
        recent_articles = _within_24h(raw_articles, window_end=None)
        logger.info(
            "24h filter (window_end=now): %d → %d articles (dropped %d old)",
            len(raw_articles),
            len(recent_articles),
            len(raw_articles) - len(recent_articles),
        )

    recent_articles = enrich_raw_articles(recent_articles)

    filtered = filter_articles(recent_articles, keywords)
    logger.info("Filtered to %d keyword-matching domestic (Korea-scoped) articles", len(filtered))

    priority_count = sum(1 for a in filtered if gov_target_score(a) > 0)
    if priority_count:
        logger.info("Gov/Fraunhofer-target articles (정부·R&D 타깃): %d", priority_count)

    if len(filtered) > _MAX_ARTICLES_PER_RUN:
        logger.info(
            "Capping summarization to top %d articles (dropped %d lower-relevance)",
            _MAX_ARTICLES_PER_RUN,
            len(filtered) - _MAX_ARTICLES_PER_RUN,
        )
        filtered = _cap_with_policy_priority(filtered, _MAX_ARTICLES_PER_RUN)
    else:
        filtered = sorted(filtered, key=_article_pipeline_sort_key)

    if not filtered:
        if window_end is not None and report_exists(log_date):
            remove_report(log_date)
            logger.info(
                "Removed stale daily report for %s (no articles for this date)",
                log_date.isoformat(),
            )
        return {
            "log_date": log_date.isoformat(),
            "fetched": len(raw_articles),
            "filtered": 0,
            "stored": 0,
        }

    # Deduplicate: skip articles whose URL was already processed on a previous run.
    store = DailyLogStore(settings.database_path)
    seen_urls = store.get_seen_urls()
    new_articles = [a for a in filtered if a.url not in seen_urls]
    skipped = len(filtered) - len(new_articles)
    if skipped:
        logger.info("Dedup filter: skipped %d already-seen article(s)", skipped)
    filtered = new_articles

    if not filtered:
        logger.info("No new articles after dedup filter — skipping summarization")
        if window_end is not None and report_exists(log_date):
            remove_report(log_date)
            logger.info(
                "Removed stale daily report for %s (all articles already processed)",
                log_date.isoformat(),
            )
        return {
            "log_date": log_date.isoformat(),
            "fetched": len(raw_articles),
            "filtered": 0,
            "stored": 0,
        }

    summarizer = Summarizer(settings)
    summarized = summarizer.summarize_batch(filtered)

    stored = store.save_entries(log_date, summarized)

    report_path = save_daily_report(log_date, summarized, top_keywords=settings.keywords[:3])

    return {
        "log_date": log_date.isoformat(),
        "fetched": len(raw_articles),
        "filtered": len(filtered),
        "summarized": len(summarized),
        "stored": stored,
        "daily_report": str(report_path) if report_path else None,
    }
