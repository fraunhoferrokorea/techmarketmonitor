from __future__ import annotations

from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse

_KOREA_KR_BASE = "https://www.korea.kr"


def canonical_article_url(url: str) -> str:
    """Normalize article URLs so RSS and archive forms dedupe correctly."""
    parsed = urlparse(urljoin(_KOREA_KR_BASE, unescape(url)))
    news_id = parse_qs(parsed.query).get("newsId", [None])[0]
    if news_id and "korea.kr" in parsed.netloc:
        return f"{_KOREA_KR_BASE}{parsed.path}?newsId={news_id}"
    return url.split("#", 1)[0].strip()
