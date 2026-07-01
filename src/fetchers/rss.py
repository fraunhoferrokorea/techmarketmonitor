from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser

from src.models import RawArticle
from src.korea_scope import filter_domestic_articles, is_foreign_url

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds


def _parse_date(entry: feedparser.FeedParserDict) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except Exception:
                pass

    return None


def _clean(text: str | None) -> str:
    return (text or "").strip()


class RSSFetcher:
    def __init__(self, name: str, url: str, category: str) -> None:
        self.name = name
        self.url = url
        self.category = category

    def fetch(self) -> list[RawArticle]:
        try:
            feed = feedparser.parse(self.url, request_headers={"User-Agent": "TechMarketMonitor/1.0"})
        except Exception as exc:
            logger.error("Failed to fetch %s (%s): %s", self.name, self.url, exc)
            return []

        if feed.bozo and not feed.entries:
            logger.warning("Malformed feed %s: %s", self.name, feed.bozo_exception)
            return []

        articles: list[RawArticle] = []
        for entry in feed.entries:
            title = _clean(getattr(entry, "title", None))
            link = _clean(getattr(entry, "link", None))
            if not title or not link:
                continue

            summary = _clean(getattr(entry, "summary", None) or getattr(entry, "description", None))
            if hasattr(entry, "content") and entry.content:
                for block in entry.content:
                    value = _clean(getattr(block, "value", None))
                    if len(value) > len(summary):
                        summary = value
            published_at = _parse_date(entry)

            articles.append(
                RawArticle(
                    title=title,
                    url=link,
                    summary=summary,
                    source_name=self.name,
                    category=self.category,
                    published_at=published_at,
                )
            )

        kept, dropped = filter_domestic_articles(articles, label=self.name)
        if dropped:
            logger.info(
                "RSS %s: excluded %d foreign/non-domestic entr%s at fetch time",
                self.name,
                dropped,
                "y" if dropped == 1 else "ies",
            )
        logger.debug("Fetched %d domestic entries from %s", len(kept), self.name)
        return kept
