from __future__ import annotations

from src.fetchers.keyword_search import KeywordSearchFetcher
from src.fetchers.rss import RSSFetcher


_NON_RSS_METHODS = frozenset({"HTML", "PACST"})


def build_fetchers(
    sources: list[dict],
    keywords: list[str],
    *,
    search_keywords: list[str] | None = None,
) -> list[RSSFetcher | KeywordSearchFetcher]:
    """Instantiate RSS fetchers for curated sources plus keyword news search.

    ``search_keywords`` (usually original labels from keywords.txt) drive Google
    News RSS discovery. ``keywords`` alone is kept for callers that only need
    curated RSS fetchers; when ``search_keywords`` is omitted, ``keywords`` is
    used for search as well.
    """
    fetchers: list[RSSFetcher | KeywordSearchFetcher] = []
    for source in sources:
        name = source.get("name", "Unknown")
        # Prefer machine feed URL when sources.md keeps a browsable list page in url.
        url = source.get("feed_url") or source.get("url", "")
        category = source.get("category", "general")
        method = (source.get("method", "GET") or "GET").upper()
        if not url or method in _NON_RSS_METHODS:
            continue
        fetchers.append(
            RSSFetcher(name=name, url=url, category=category, method=method)
        )

    query_keywords = search_keywords if search_keywords is not None else keywords
    if query_keywords:
        fetchers.append(KeywordSearchFetcher(query_keywords))
    return fetchers
