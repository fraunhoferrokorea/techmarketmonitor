from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import feedparser
import httpx

from src.fetchers.rss import _clean, _parse_date
from src.korea_scope import filter_domestic_articles
from src.models import RawArticle

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0
_USER_AGENT = "TechMarketMonitor/1.0"
_BATCH_EXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_LOOKBACK_DAYS = 7
_MAX_RESOLVE_PER_RUN = 80


def _search_query_variants(keyword: str) -> list[str]:
    """Original + whitespace-stripped forms so spaced/unspaced Korean both hit."""
    raw = (keyword or "").strip()
    if not raw:
        return []
    compact = re.sub(r"\s+", "", raw)
    variants: list[str] = []
    for form in (raw, compact):
        if form and form not in variants:
            variants.append(form)
    return variants


def google_news_search_url(keyword: str, *, days: int = _LOOKBACK_DAYS) -> str:
    """Build a Google News RSS search URL for one monitoring keyword (KR locale).

    OR-combines spaced and unspaced forms so ``에너지고속도로`` also finds
    ``에너지 고속도로`` (and the reverse).
    """
    variants = _search_query_variants(keyword)
    if not variants:
        variants = [keyword]
    # Quoted phrases keep multi-word English (Digital Grid); unquoted compact
    # helps Korean compounds match regardless of publisher spacing.
    clauses: list[str] = []
    for form in variants:
        quoted = f'"{form}"'
        if quoted not in clauses:
            clauses.append(quoted)
        if " " not in form and form not in clauses:
            clauses.append(form)
    q = f'({" OR ".join(clauses)}) when:{max(1, days)}d'
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    )


def _article_id(url: str) -> str | None:
    match = re.search(r"/articles/([^?/]+)", url)
    return match.group(1) if match else None


def resolve_google_news_url(article_url: str, *, timeout: float = _TIMEOUT) -> str | None:
    """Resolve a post-2024 Google News ``articles/CBMi…`` link to the publisher URL."""
    article_id = _article_id(article_url)
    if not article_id:
        return None

    headers = {"User-Agent": _USER_AGENT}
    try:
        with httpx.Client(
            timeout=timeout, headers=headers, follow_redirects=True
        ) as client:
            page = client.get(article_url)
            page.raise_for_status()
            sig = re.search(r'data-n-a-sg="([^"]+)"', page.text)
            ts = re.search(r'data-n-a-ts="([^"]+)"', page.text)
            if not sig or not ts:
                return None

            rpc_inner = json.dumps(
                [
                    "garturlreq",
                    [
                        [
                            "X",
                            "X",
                            ["X", "X"],
                            None,
                            None,
                            1,
                            1,
                            "US:en",
                            None,
                            1,
                            None,
                            None,
                            None,
                            None,
                            None,
                            0,
                            1,
                        ],
                        "X",
                        "X",
                        1,
                        [1, 1, 1],
                        1,
                        1,
                        None,
                        0,
                        0,
                        None,
                        0,
                    ],
                    article_id,
                    int(ts.group(1)),
                    sig.group(1),
                ],
                separators=(",", ":"),
            )
            f_req = json.dumps(
                [[["Fbv4je", rpc_inner, None, "generic"]]],
                separators=(",", ":"),
            )
            response = client.post(
                _BATCH_EXECUTE_URL,
                data={"f.req": f_req},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Referer": "https://news.google.com/",
                },
            )
            response.raise_for_status()
            body = response.text
    except Exception as exc:
        logger.debug("Google News URL resolve failed for %s: %s", article_url[:80], exc)
        return None

    if body.startswith(")]}'"):
        body = body.split("\n", 1)[1]
    body = body.lstrip()
    head, _, tail = body.partition("\n")
    if head.strip().isdigit():
        body = tail

    try:
        envelopes = json.loads(body)
    except json.JSONDecodeError:
        return None

    for env in envelopes:
        if (
            isinstance(env, list)
            and len(env) >= 3
            and env[0] == "wrb.fr"
            and env[1] == "Fbv4je"
        ):
            try:
                payload = json.loads(env[2])
            except (TypeError, json.JSONDecodeError):
                continue
            if payload and payload[0] == "garturlres" and isinstance(payload[1], str):
                return payload[1]
    return None


def _publisher_name(entry: feedparser.FeedParserDict) -> str:
    source = getattr(entry, "source", None)
    if source is None:
        return ""
    if isinstance(source, dict):
        return _clean(source.get("title"))
    return _clean(getattr(source, "title", None))


def _within_lookback(published_at: datetime | None, *, days: int) -> bool:
    if published_at is None:
        return True
    now = datetime.now(tz=timezone.utc)
    published = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
    return published >= now - timedelta(days=days)


class KeywordSearchFetcher:
    """Fetch Korean news via Google News RSS search for each monitoring keyword."""

    def __init__(
        self,
        keywords: list[str],
        *,
        days: int = _LOOKBACK_DAYS,
        resolve_urls: bool = True,
        max_resolve: int = _MAX_RESOLVE_PER_RUN,
    ) -> None:
        self.keywords = [k for k in keywords if k and k.strip()]
        self.days = days
        self.resolve_urls = resolve_urls
        self.max_resolve = max_resolve
        self.name = "키워드 뉴스검색"
        self.url = "https://news.google.com/rss/search"
        self.category = "korean"
        self.method = "GET"

    def fetch(self) -> list[RawArticle]:
        if not self.keywords:
            return []

        candidates: list[tuple[str, RawArticle]] = []
        seen_titles: set[str] = set()

        for keyword in self.keywords:
            feed_url = google_news_search_url(keyword, days=self.days)
            try:
                feed = feedparser.parse(
                    feed_url, request_headers={"User-Agent": _USER_AGENT}
                )
            except Exception as exc:
                logger.error("Keyword search failed for %r: %s", keyword, exc)
                continue

            if feed.bozo and not feed.entries:
                logger.warning(
                    "Malformed keyword feed for %r: %s",
                    keyword,
                    feed.bozo_exception,
                )
                continue

            added = 0
            for entry in feed.entries:
                title = _clean(getattr(entry, "title", None))
                link = _clean(getattr(entry, "link", None))
                if not title or not link:
                    continue
                title_key = re.sub(r"\s+", " ", title).casefold()
                if title_key in seen_titles:
                    continue

                published_at = _parse_date(entry)
                if not _within_lookback(published_at, days=self.days):
                    continue

                publisher = _publisher_name(entry) or f"뉴스검색·{keyword}"
                summary = _clean(
                    getattr(entry, "summary", None)
                    or getattr(entry, "description", None)
                )
                # Strip Google News HTML wrapper from summary when present.
                summary = re.sub(r"<[^>]+>", " ", summary)
                summary = " ".join(summary.split())

                seen_titles.add(title_key)
                candidates.append(
                    (
                        link,
                        RawArticle(
                            title=title,
                            url=link,
                            summary=summary,
                            source_name=publisher,
                            category=self.category,
                            published_at=published_at,
                        ),
                    )
                )
                added += 1

            logger.info(
                "Keyword search %r: %d new candidate(s)",
                keyword,
                added,
            )

        if not candidates:
            return []

        articles: list[RawArticle] = []
        resolve_budget = self.max_resolve if self.resolve_urls else 0
        resolved = 0
        unresolved = 0

        for gnews_url, article in candidates:
            final_url = article.url
            if self.resolve_urls and "news.google.com" in urlparse(gnews_url).netloc:
                if resolved >= resolve_budget:
                    unresolved += 1
                    continue
                decoded = resolve_google_news_url(gnews_url)
                resolved += 1
                if not decoded:
                    unresolved += 1
                    continue
                final_url = decoded

            if "news.google.com" in urlparse(final_url).netloc:
                unresolved += 1
                continue

            articles.append(
                RawArticle(
                    title=article.title,
                    url=final_url,
                    summary=article.summary,
                    source_name=article.source_name,
                    category=article.category,
                    published_at=article.published_at,
                )
            )

        if resolved or unresolved:
            logger.info(
                "Keyword search URL resolve: ok=%d unresolved/skipped=%d (budget=%d)",
                len(articles),
                unresolved,
                resolve_budget,
            )

        kept, dropped = filter_domestic_articles(articles, label=self.name)
        if dropped:
            logger.info(
                "Keyword search: excluded %d foreign/non-domestic after resolve",
                dropped,
            )
        logger.info("Keyword search: %d domestic article(s) from %d keywords", len(kept), len(self.keywords))
        return kept
