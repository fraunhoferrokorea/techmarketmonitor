from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from html import unescape
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from src.models import RawArticle
from src.url_utils import canonical_article_url

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
_BASE = "https://www.korea.kr"
_TIMEOUT = 30.0
_USER_AGENT = "TechMarketMonitor/1.0"

_LIST_PATHS = (
    ("/news/policyNewsList.do", "정책브리핑 정책뉴스"),
    ("/briefing/pressReleaseList.do", "정책브리핑 보도자료"),
    ("/briefing/actuallyList.do", "정책브리핑 설명자료"),
    ("/archive/expDocList.do", "정책브리핑 전문자료"),
)

_EXPDOC_ITEM_RE = re.compile(
    r'<td class="subject"><a href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a></td>\s*'
    r"<td>(?P<org>.*?)</td>\s*"
    r"<td>(?P<published>[\d.]+)</td>",
    re.S,
)

_ITEM_RE = re.compile(
    r'<li>\s*<a href="(?P<href>[^"]+)">\s*<span class="text">\s*'
    r"<strong>(?P<title>.*?)</strong>\s*"
    r'<span class="lead">\s*(?P<summary>.*?)\s*</span>\s*'
    r'<span class="source">\s*<span>(?P<published>[\d.]+)</span>\s*'
    r"<span>(?P<org>.*?)</span>",
    re.S,
)


def _canonical_url(url: str) -> str:
    return canonical_article_url(url)


def _parse_published(raw: str, log_date: date) -> datetime:
    raw = raw.strip()
    try:
        published = datetime.strptime(raw, "%Y.%m.%d").replace(tzinfo=KST)
        return published
    except ValueError:
        return datetime(
            log_date.year,
            log_date.month,
            log_date.day,
            12,
            0,
            tzinfo=KST,
        ).astimezone(timezone.utc)


def _fetch_list_page(path: str, log_date: date, page_index: int) -> str:
    params = {
        "pageIndex": page_index,
        "startDate": log_date.isoformat(),
        "endDate": log_date.isoformat(),
    }
    if path == "/archive/expDocList.do":
        params["group"] = "T"
    response = httpx.get(
        urljoin(_BASE, path),
        params=params,
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    return response.text


def _parse_expdoc_page(html: str, log_date: date, seen_urls: set[str]) -> list[RawArticle]:
    articles: list[RawArticle] = []
    for match in _EXPDOC_ITEM_RE.finditer(html):
        href = unescape(match.group("href"))
        url = _canonical_url(href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = re.sub(r"\s+", " ", unescape(match.group("title"))).strip()
        org = re.sub(r"\s+", " ", unescape(match.group("org"))).strip()
        source_name = f"정책브리핑 전문자료 {org}" if org else "정책브리핑 전문자료"
        published_at = _parse_published(match.group("published"), log_date)

        articles.append(
            RawArticle(
                title=title,
                url=url,
                summary=f"{title} — {org} 전문자료",
                source_name=source_name,
                category="korean",
                published_at=published_at,
            )
        )
    return articles


def fetch_korea_kr_for_date(log_date: date) -> list[RawArticle]:
    """Fetch policy/briefing articles from korea.kr for one calendar day."""
    articles: list[RawArticle] = []
    seen_urls: set[str] = set()

    for path, default_source in _LIST_PATHS:
        empty_pages = 0
        for page_index in range(1, 51):
            try:
                html = _fetch_list_page(path, log_date, page_index)
            except Exception as exc:
                logger.warning("korea.kr archive fetch failed (%s p%d): %s", path, page_index, exc)
                break

            matches = list(_ITEM_RE.finditer(html))
            if path == "/archive/expDocList.do":
                page_articles = _parse_expdoc_page(html, log_date, seen_urls)
                if not page_articles:
                    empty_pages += 1
                    if empty_pages >= 2:
                        break
                    continue
                empty_pages = 0
                articles.extend(page_articles)
                continue

            if not matches:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                continue
            empty_pages = 0

            new_on_page = 0
            for match in matches:
                href = unescape(match.group("href"))
                url = _canonical_url(href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                new_on_page += 1

                title = re.sub(r"\s+", " ", unescape(match.group("title"))).strip()
                summary = re.sub(r"\s+", " ", unescape(match.group("summary"))).strip()
                org = re.sub(r"\s+", " ", unescape(match.group("org"))).strip()
                source_name = f"정책브리핑 {org}" if org else default_source
                published_at = _parse_published(match.group("published"), log_date)

                articles.append(
                    RawArticle(
                        title=title,
                        url=url,
                        summary=summary,
                        source_name=source_name,
                        category="korean",
                        published_at=published_at,
                    )
                )

            if new_on_page == 0:
                break

    logger.info(
        "korea.kr archive (log_date=%s): fetched %d article(s)",
        log_date.isoformat(),
        len(articles),
    )
    return articles
