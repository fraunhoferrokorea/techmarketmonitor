"""HTML board scrapers for ministry/agency press pages without reliable RSS."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from html import unescape
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from src.models import RawArticle

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
_TIMEOUT = 30.0
_USER_AGENT = "TechMarketMonitor/1.0"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _parse_day(raw: str) -> date | None:
    raw = raw.strip().rstrip(".")
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _published_at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=KST).astimezone(timezone.utc)


def _get(url: str, *, params: dict | None = None) -> str:
    response = httpx.get(
        url,
        params=params,
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    return response.text


def _strip_jsession(url: str) -> str:
    return re.sub(r";jsessionid=[^?]*", "", url, flags=re.I)


# ── parsers ──────────────────────────────────────────────────────────────

_MOLIT_RE = re.compile(
    r'<a href="(?P<href>dtl\.jsp\?[^"]+)"[^>]*>\s*(?P<title>.*?)\s*</a>.*?'
    r'<td class="bd_date">(?P<published>\d{4}-\d{2}-\d{2})</td>',
    re.S,
)

_MND_RE = re.compile(
    r'<a href="(?P<href>/bbs/mnd/[^"]+/artclView\.do)"[^>]*>\s*'
    r"<strong><span>(?P<title>.*?)</span></strong>.*?"
    r'<td class="td-date">(?P<published>\d{4}\.\d{2}\.\d{2})</td>',
    re.S,
)

_KASA_RE = re.compile(
    r"""onclick="fn_view\('(?P<id>\d+)'\);[^"]*"[^>]*>.*?"""
    r'<strong class="board__subject-text">(?P<title>.*?)</strong>.*?'
    r'class="board__table--date">\s*(?P<published>\d{4}-\d{2}-\d{2})\s*<',
    re.S,
)

_TIPA_RE = re.compile(
    r"""href=['"](?P<href>/s040102/view/id/\d+)['"][^>]*>\s*(?P<title>.*?)\s*</a>.*?"""
    r"<td[^>]*>\s*(?P<published>\d{4}\.\d{2}\.\d{2})\s*</td>",
    re.S,
)

_EKN_RE = re.compile(
    r'href="//(?:www\.)?ekn\.kr/web/view\.php\?key=(?P<key>\d+)"[^>]*>\s*(?P<title>.*?)\s*</a>',
    re.S,
)

_KETEP_RE = re.compile(
    r'href="(?P<href>/board/view\?menuId=MENU002070200000000[^"]+)"[^>]*>\s*(?P<title>.*?)\s*</a>',
    re.S,
)


def _parse_molit(html: str, seen: set[str]) -> list[tuple[str, str, date]]:
    base = "https://www.molit.go.kr/USR/NEWS/m_71/"
    rows: list[tuple[str, str, date]] = []
    for match in _MOLIT_RE.finditer(html):
        day = _parse_day(match.group("published"))
        if not day:
            continue
        url = _strip_jsession(urljoin(base, unescape(match.group("href"))))
        title = _clean(re.sub(r"<[^>]+>", "", match.group("title")))
        if not title or url in seen:
            continue
        seen.add(url)
        rows.append((title, url, day))
    return rows


def _parse_mnd(html: str, seen: set[str]) -> list[tuple[str, str, date]]:
    rows: list[tuple[str, str, date]] = []
    for match in _MND_RE.finditer(html):
        day = _parse_day(match.group("published"))
        if not day:
            continue
        url = _strip_jsession(urljoin("https://www.mnd.go.kr", unescape(match.group("href"))))
        title = _clean(match.group("title"))
        if not title or url in seen:
            continue
        seen.add(url)
        rows.append((title, url, day))
    return rows


def _parse_kasa(html: str, seen: set[str]) -> list[tuple[str, str, date]]:
    rows: list[tuple[str, str, date]] = []
    for match in _KASA_RE.finditer(html):
        day = _parse_day(match.group("published"))
        if not day:
            continue
        url = (
            "https://www.kasa.go.kr/prog/plcyBrf/brief/kor/sub01_01_04/view.do"
            f"?plcyBrfNo={match.group('id')}"
        )
        title = _clean(match.group("title"))
        if not title or url in seen:
            continue
        seen.add(url)
        rows.append((title, url, day))
    return rows


def _parse_tipa(html: str, seen: set[str]) -> list[tuple[str, str, date]]:
    rows: list[tuple[str, str, date]] = []
    for match in _TIPA_RE.finditer(html):
        day = _parse_day(match.group("published"))
        if not day:
            continue
        url = urljoin("https://www.tipa.or.kr", unescape(match.group("href")))
        title = _clean(match.group("title"))
        if not title or url in seen:
            continue
        seen.add(url)
        rows.append((title, url, day))
    return rows


def _parse_ekn(html: str, seen: set[str]) -> list[tuple[str, str, date]]:
    rows: list[tuple[str, str, date]] = []
    for match in _EKN_RE.finditer(html):
        key = match.group("key")
        # key prefix YYYYMMDD…
        day = _parse_day(f"{key[:4]}-{key[4:6]}-{key[6:8]}")
        if not day:
            continue
        url = f"https://www.ekn.kr/web/view.php?key={key}"
        title = _clean(re.sub(r"<[^>]+>", "", match.group("title")))
        if not title or url in seen:
            continue
        seen.add(url)
        rows.append((title, url, day))
    return rows


def _parse_ketep(html: str, seen: set[str]) -> list[tuple[str, str, date]]:
    """Homepage teaser links — date unknown; treat as today when recent-only."""
    rows: list[tuple[str, str, date]] = []
    today = datetime.now(tz=KST).date()
    for match in _KETEP_RE.finditer(html):
        url = urljoin("https://www.ketep.re.kr", unescape(match.group("href")))
        title = _clean(re.sub(r"<[^>]+>", "", match.group("title")))
        if not title or url in seen:
            continue
        seen.add(url)
        rows.append((title, url, today))
    return rows


class _Board:
    def __init__(
        self,
        name: str,
        list_url: str,
        parser,
        *,
        page_param: str | None = None,
        max_pages: int = 5,
    ) -> None:
        self.name = name
        self.list_url = list_url
        self.parser = parser
        self.page_param = page_param
        self.max_pages = max_pages


_BOARDS: tuple[_Board, ...] = (
    _Board(
        "국토교통부 보도자료",
        "https://www.molit.go.kr/USR/NEWS/m_71/lst.jsp",
        _parse_molit,
        page_param="lcmspage",
        max_pages=5,
    ),
    _Board(
        "국방부 보도자료",
        "https://www.mnd.go.kr/mnd/167/subview.do",
        _parse_mnd,
        page_param="page",
        max_pages=5,
    ),
    _Board(
        "우주항공청 보도자료",
        "https://www.kasa.go.kr/prog/plcyBrf/brief/kor/sub01_01_04/list.do",
        _parse_kasa,
        page_param="pageIndex",
        max_pages=5,
    ),
    _Board(
        "TIPA 보도자료",
        "https://www.tipa.or.kr/s040102",
        _parse_tipa,
        page_param="page",
        max_pages=3,
    ),
    _Board(
        "에너지경제신문",
        "https://www.ekn.kr/web/",
        _parse_ekn,
        max_pages=1,
    ),
    _Board(
        "KETEP 보도자료",
        "https://www.ketep.re.kr/",
        _parse_ketep,
        max_pages=1,
    ),
)


def _rows_to_articles(
    rows: list[tuple[str, str, date]],
    *,
    source_name: str,
    log_date: date | None,
) -> list[RawArticle]:
    articles: list[RawArticle] = []
    for title, url, day in rows:
        if log_date is not None and day != log_date:
            continue
        articles.append(
            RawArticle(
                title=title,
                url=url,
                summary=title,
                source_name=source_name,
                category="korean",
                published_at=_published_at(day),
            )
        )
    return articles


def _fetch_board_pages(board: _Board, *, log_date: date | None) -> list[RawArticle]:
    articles: list[RawArticle] = []
    seen: set[str] = set()
    empty_streak = 0

    for page in range(1, board.max_pages + 1):
        params = {board.page_param: page} if board.page_param and page > 1 else None
        try:
            html = _get(board.list_url, params=params)
        except Exception as exc:
            logger.warning("HTML board fetch failed (%s p%d): %s", board.name, page, exc)
            break

        rows = board.parser(html, seen)
        page_articles = _rows_to_articles(rows, source_name=board.name, log_date=log_date)

        if log_date is not None:
            # Stop when all rows on the page are older than the target day.
            if rows and all(day < log_date for _, _, day in rows):
                break
            if not page_articles:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                continue
            empty_streak = 0
            articles.extend(page_articles)
        else:
            articles.extend(page_articles)
            if not rows:
                break

    return articles


def fetch_html_boards_recent() -> list[RawArticle]:
    """Fetch recent items from HTML-only ministry/agency/media boards."""
    articles: list[RawArticle] = []
    for board in _BOARDS:
        try:
            found = _fetch_board_pages(board, log_date=None)
            articles.extend(found)
            logger.info("HTML board %s: fetched %d recent item(s)", board.name, len(found))
        except Exception as exc:
            logger.warning("HTML board %s failed: %s", board.name, exc)
    return articles


def fetch_html_boards_for_date(log_date: date) -> list[RawArticle]:
    """Fetch HTML board items published on one calendar day (catch-up)."""
    articles: list[RawArticle] = []
    for board in _BOARDS:
        # Homepage teasers without reliable dates are skipped in catch-up.
        if board.name in {"KETEP 보도자료"}:
            continue
        try:
            found = _fetch_board_pages(board, log_date=log_date)
            articles.extend(found)
            if found:
                logger.info(
                    "HTML board %s (log_date=%s): %d item(s)",
                    board.name,
                    log_date.isoformat(),
                    len(found),
                )
        except Exception as exc:
            logger.warning("HTML board %s failed: %s", board.name, exc)
    return articles
