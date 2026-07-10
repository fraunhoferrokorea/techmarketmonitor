from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import feedparser
import httpx

from src.models import RawArticle
from src.korea_scope import filter_domestic_articles

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0
_USER_AGENT = "TechMarketMonitor/1.0"


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


def _absolute_url(link: str, base_url: str) -> str:
    link = link.strip()
    if not link:
        return link
    if link.startswith("//"):
        link = "https:" + link
    parsed = urlparse(link)
    if not (parsed.scheme and parsed.netloc):
        link = urljoin(base_url, link)
    # Drop servlet session tokens that break sharing / dedup.
    return re.sub(r";jsessionid=[^?]*", "", link, flags=re.I)


class RSSFetcher:
    def __init__(
        self,
        name: str,
        url: str,
        category: str,
        *,
        method: str = "GET",
    ) -> None:
        self.name = name
        self.url = url
        self.category = category
        self.method = (method or "GET").upper()

    def fetch(self) -> list[RawArticle]:
        try:
            headers = {"User-Agent": _USER_AGENT}
            if self.method == "POST":
                response = httpx.post(
                    self.url,
                    timeout=_TIMEOUT,
                    follow_redirects=True,
                    headers=headers,
                )
                response.raise_for_status()
                feed = feedparser.parse(response.content)
            else:
                feed = feedparser.parse(self.url, request_headers=headers)
        except Exception as exc:
            logger.error("Failed to fetch %s (%s): %s", self.name, self.url, exc)
            return []

        if feed.bozo and not feed.entries:
            logger.warning("Malformed feed %s: %s", self.name, feed.bozo_exception)
            return []

        articles: list[RawArticle] = []
        for entry in feed.entries:
            title = _clean(getattr(entry, "title", None))
            link = _absolute_url(_clean(getattr(entry, "link", None)), self.url)
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
