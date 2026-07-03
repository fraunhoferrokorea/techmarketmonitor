from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

from src.models import RawArticle

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
_BASE = "https://www.pacst.go.kr"
_TIMEOUT = 30.0
_USER_AGENT = "TechMarketMonitor/1.0"

# (section, board_id, source label)
_BOARDS: tuple[tuple[str, int, str], ...] = (
    ("board", 4, "PACST 보도자료"),
    ("board", 3, "PACST 공지사항"),
    ("board", 2, "PACST 정책 및 연구 동향"),
    ("adv", 2, "PACST 심의회의"),
    ("adv", 1, "PACST 자문회의"),
)

_LIST_ITEM_RE = re.compile(
    r'<li class="pacst-board-list__item">\s*'
    r'<a href="(?P<href>[^"]+)">\s*'
    r"<strong>[^<]*</strong>\s*"
    r'<div class="pacst-board-list__item-text">\s*'
    r"<p>(?P<title>.*?)</p>\s*"
    r"</div>\s*"
    r"<span>(?P<published>\d{4}-\d{2}-\d{2})</span>",
    re.S,
)

_THUMB_ITEM_RE = re.compile(
    r'<li class="pacst-board-thumb__item">\s*'
    r'<a href="(?P<href>[^"]+)">.*?'
    r"<p>(?P<title>.*?)</p>\s*"
    r"<span>(?P<published>\d{4}-\d{2}-\d{2})</span>",
    re.S,
)


def _canonical_url(href: str, section: str) -> str:
    full = urljoin(f"{_BASE}/jsp/{section}/", unescape(href))
    parsed = urlparse(full)
    qs = parse_qs(parsed.query)
    post_id = qs.get("post_id", [None])[0]
    board_id = qs.get("board_id", [None])[0]
    if post_id and board_id:
        view = "boardView.jsp" if section == "board" else "advboardView.jsp"
        return f"{_BASE}/jsp/{section}/{view}?post_id={post_id}&board_id={board_id}"
    return full.split("#", 1)[0].strip()


def _parse_published(raw: str) -> datetime:
    published = datetime.strptime(raw.strip(), "%Y-%m-%d").replace(tzinfo=KST)
    return published.astimezone(timezone.utc)


def _clean_title(raw: str) -> str:
    return re.sub(r"\s+", " ", unescape(raw)).strip()


def _fetch_board_page(section: str, board_id: int, page_index: int) -> str:
    list_name = "boardList.jsp" if section == "board" else "advboardList.jsp"
    response = httpx.get(
        urljoin(_BASE, f"/jsp/{section}/{list_name}"),
        params={"board_id": board_id, "cpage": page_index},
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    return response.text


def _parse_board_page(
    html: str,
    *,
    section: str,
    source_name: str,
    log_date: date,
    seen_urls: set[str],
) -> tuple[list[RawArticle], bool]:
    """Return articles for log_date and whether the page is entirely before log_date."""
    articles: list[RawArticle] = []
    matches: list[re.Match[str]] = []
    matches.extend(_LIST_ITEM_RE.finditer(html))
    matches.extend(_THUMB_ITEM_RE.finditer(html))

    if not matches:
        return [], False

    all_before = True
    for match in matches:
        published_raw = match.group("published")
        published_day = datetime.strptime(published_raw, "%Y-%m-%d").date()
        if published_day > log_date:
            all_before = False
            continue
        if published_day < log_date:
            continue

        all_before = False
        url = _canonical_url(match.group("href"), section)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = _clean_title(match.group("title"))
        articles.append(
            RawArticle(
                title=title,
                url=url,
                summary=title,
                source_name=source_name,
                category="korean",
                published_at=_parse_published(published_raw),
            )
        )

    return articles, all_before and bool(matches)


def fetch_pacst_for_date(log_date: date) -> list[RawArticle]:
    """Fetch PACST board posts published on one calendar day."""
    articles: list[RawArticle] = []
    seen_urls: set[str] = set()

    for section, board_id, source_name in _BOARDS:
        empty_pages = 0
        for page_index in range(1, 31):
            try:
                html = _fetch_board_page(section, board_id, page_index)
            except Exception as exc:
                logger.warning(
                    "PACST fetch failed (%s board_id=%d p%d): %s",
                    section,
                    board_id,
                    page_index,
                    exc,
                )
                break

            page_articles, all_before = _parse_board_page(
                html,
                section=section,
                source_name=source_name,
                log_date=log_date,
                seen_urls=seen_urls,
            )

            if all_before:
                break

            if not page_articles:
                empty_pages += 1
                if empty_pages >= 3:
                    break
                continue

            empty_pages = 0
            articles.extend(page_articles)

    logger.info(
        "PACST archive (log_date=%s): fetched %d article(s)",
        log_date.isoformat(),
        len(articles),
    )
    return articles
