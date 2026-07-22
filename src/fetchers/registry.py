from __future__ import annotations

from src.fetchers.rss import RSSFetcher


_NON_RSS_METHODS = frozenset({"HTML", "PACST"})


def build_fetchers(sources: list[dict], keywords: list[str]) -> list[RSSFetcher]:
    """Instantiate one RSSFetcher per RSS/Atom source entry."""
    fetchers: list[RSSFetcher] = []
    for source in sources:
        name = source.get("name", "Unknown")
        # Prefer machine feed URL when sources.txt keeps a browsable list page in url.
        url = source.get("feed_url") or source.get("url", "")
        category = source.get("category", "general")
        method = (source.get("method", "GET") or "GET").upper()
        if not url or method in _NON_RSS_METHODS:
            continue
        fetchers.append(
            RSSFetcher(name=name, url=url, category=category, method=method)
        )
    return fetchers
