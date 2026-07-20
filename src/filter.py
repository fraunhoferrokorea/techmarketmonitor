from __future__ import annotations

import logging
import re

from src.korea_scope import is_domestic_news
from src.models import FilteredArticle, RawArticle
from src.policy_priority import (
    gov_target_pass_label,
    is_gov_target,
    passes_gov_collection_exception,
)
from src.rd_targeting import is_excluded_rd_news

logger = logging.getLogger(__name__)

_HTML_TAG = re.compile(r"<[^>]+>")


def _normalize(text: str) -> str:
    cleaned = _HTML_TAG.sub(" ", text)
    return " ".join(cleaned.lower().split())


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    normalized = _normalize(text)
    return [keyword for keyword in keywords if keyword in normalized]


def passes_collection_filter(
    article: RawArticle,
    keywords: list[str],
    required_keywords: list[str] | None = None,
) -> bool:
    """True when article would pass fetch-time keyword collection filter.

    Required keywords (normally the full keywords.txt list) must match unless
    the item is a gov/R&D target that also has an energy·grid domain hint
    (or explicit Fraunhofer mention).
    """
    if is_excluded_rd_news(article):
        return False

    searchable = " ".join([article.title, article.summary, article.source_name])
    core = required_keywords or []
    gov_exception = passes_gov_collection_exception(article)
    if core and not match_keywords(searchable, core) and not gov_exception:
        return False
    if match_keywords(searchable, keywords) or gov_exception:
        return True
    return False


def filter_articles(
    articles: list[RawArticle],
    keywords: list[str],
    required_keywords: list[str] | None = None,
) -> list[FilteredArticle]:
    filtered: list[FilteredArticle] = []
    seen_urls: set[str] = set()
    target_label = gov_target_pass_label()
    dropped_foreign = 0
    dropped_non_rd = 0
    dropped_core = 0
    dropped_keywords = 0
    core = required_keywords or []

    for article in articles:
        if article.url in seen_urls:
            continue

        if not is_domestic_news(article):
            dropped_foreign += 1
            continue

        if is_excluded_rd_news(article):
            dropped_non_rd += 1
            continue

        searchable = " ".join([article.title, article.summary, article.source_name])
        if not passes_collection_filter(article, keywords, core):
            if core:
                dropped_core += 1
            else:
                dropped_keywords += 1
            continue

        matched = match_keywords(searchable, keywords)
        if not matched and is_gov_target(article):
            matched = [target_label]

        seen_urls.add(article.url)
        filtered.append(
            FilteredArticle(
                title=article.title,
                url=article.url,
                summary=article.summary,
                source_name=article.source_name,
                category=article.category,
                published_at=article.published_at,
                matched_keywords=matched,
            )
        )

    if dropped_foreign:
        logger.info(
            "Keyword filter: excluded %d non-domestic (foreign) article(s)",
            dropped_foreign,
        )
    if dropped_non_rd:
        logger.info(
            "Keyword filter: excluded %d non-R&D article(s) (education/career or research-outcome only)",
            dropped_non_rd,
        )
    if dropped_core:
        logger.info(
            "Keyword filter: excluded %d domestic article(s) with no required keyword match (%d keywords)",
            dropped_core,
            len(core),
        )
    if dropped_keywords:
        logger.debug(
            "Keyword filter: excluded %d domestic article(s) with no keyword match",
            dropped_keywords,
        )

    return filtered
