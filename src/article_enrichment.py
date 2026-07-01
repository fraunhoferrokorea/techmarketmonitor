from __future__ import annotations

import logging
import re
from html import unescape

import httpx

from src.attachment_extractor import discover_pdf_urls, fetch_pdf_texts
from src.models import RawArticle
from src.policy_priority import is_gov_target, is_official_government_source

logger = logging.getLogger(__name__)

_MIN_SUMMARY_LEN = 600
_MAX_BODY_LEN = 8000
_MAX_MERGED_LEN = 16000
_TIMEOUT = 20.0
_USER_AGENT = "TechMarketMonitor/1.0"

_GOV_URL_TOKENS = (
    ".go.kr",
    "korea.kr",
    "msit.go.kr",
    "motie.go.kr",
    "kats.go.kr",
    "kistep.re.kr",
    "kipo.go.kr",
)

_BODY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'class="view_con"[^>]*>(.*?)</div>', re.S | re.I),
    re.compile(r'class="db_data"[^>]*>(.*?)</div>', re.S | re.I),
    re.compile(r'class="article_body"[^>]*>(.*?)</div>', re.S | re.I),
    re.compile(r'class="press_release"[^>]*>(.*?)</div>', re.S | re.I),
    re.compile(r'id="content"[^>]*>(.*?)</div>', re.S | re.I),
    re.compile(r'class="board_view"[^>]*>(.*?)</div>', re.S | re.I),
    re.compile(r'class="view_cont"[^>]*>(.*?)</div>', re.S | re.I),
]

_STRIP_BLOCK_TAGS = re.compile(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(html: str) -> str:
    cleaned = _STRIP_BLOCK_TAGS.sub(" ", html)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_body(html: str) -> str:
    for pattern in _BODY_PATTERNS:
        match = pattern.search(html)
        if match:
            text = _html_to_text(match.group(1))
            if len(text) >= 200:
                return text
    return _html_to_text(html)


def _is_government_url(url: str) -> bool:
    lower = url.lower()
    return any(token in lower for token in _GOV_URL_TOKENS)


def _should_enrich(article: RawArticle) -> bool:
    if not _is_government_url(article.url) and not is_official_government_source(article):
        return False
    if is_gov_target(article) or is_official_government_source(article):
        return True
    return len(article.summary.strip()) < _MIN_SUMMARY_LEN


def _fetch_page_html(url: str) -> str:
    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
    except Exception as exc:
        logger.debug("Could not fetch article page (%s): %s", url, exc)
        return ""

    encoding = response.encoding or "utf-8"
    try:
        return response.content.decode(encoding, errors="replace")
    except LookupError:
        return response.text


def _merge_parts(base: str, html_body: str, pdf_texts: list[str]) -> str:
    sections = [base.strip()]
    if html_body and html_body not in base:
        sections.append(html_body)
    for index, pdf_text in enumerate(pdf_texts, start=1):
        if pdf_text and pdf_text not in base:
            sections.append(f"[첨부 PDF 원문 {index}]\n{pdf_text}")
    merged = "\n\n".join(part for part in sections if part).strip()
    if len(merged) > _MAX_MERGED_LEN:
        merged = merged[:_MAX_MERGED_LEN].rsplit(" ", 1)[0] + "…"
    return merged


def enrich_raw_article(article: RawArticle) -> RawArticle:
    """Fetch HTML body and attached PDF text for government press releases."""
    if not _should_enrich(article):
        return article

    html = _fetch_page_html(article.url)
    if not html:
        return article

    html_body = ""
    if len(article.summary.strip()) < _MIN_SUMMARY_LEN or is_gov_target(article):
        html_body = _extract_body(html)
        if len(html_body) > _MAX_BODY_LEN:
            html_body = html_body[:_MAX_BODY_LEN].rsplit(" ", 1)[0] + "…"

    pdf_urls = discover_pdf_urls(html, article.url)
    pdf_texts = fetch_pdf_texts(pdf_urls) if pdf_urls else []

    if not html_body and not pdf_texts:
        return article

    merged = _merge_parts(article.summary, html_body, pdf_texts)
    if merged == article.summary.strip():
        return article

    logger.info(
        "Enriched article (%s → %d chars, PDFs=%d): %s",
        len(article.summary),
        len(merged),
        len(pdf_texts),
        article.title[:60],
    )
    return RawArticle(
        title=article.title,
        url=article.url,
        summary=merged,
        source_name=article.source_name,
        category=article.category,
        published_at=article.published_at,
    )


def enrich_raw_articles(articles: list[RawArticle]) -> list[RawArticle]:
    return [enrich_raw_article(a) for a in articles]
