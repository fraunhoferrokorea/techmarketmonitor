#!/usr/bin/env python3
"""Backfill June 2026 keyword-matching articles missed when daily generation was down.

Korea-scoped media only (arxiv stays blocked by korea_scope foreign-URL policy).
"""
from __future__ import annotations

from dataclasses import replace
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.article_enrichment import enrich_raw_article
from src.config import load_settings
from src.daily_sync import rebuild_markdown_from_db
from src.filter import filter_articles
from src.korea_scope import filter_domestic_articles
from src.models import FilteredArticle, RawArticle, SummarizedArticle
from src.rd_targeting import compute_rd_match_score
from src.storage import DailyLogStore
from src.summarizer import Summarizer
from src.url_utils import canonical_article_url

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_june2026")

KST = ZoneInfo("Asia/Seoul")

# Hand-curated June 2026 hits matching keywords.txt (HVDC / energy highway / grid).
_ITEMS: list[dict] = [
    {
        "log_date": date(2026, 6, 11),
        "title": "[단독] 3천억 규모 ‘동해안~동서울 HVDC’ 케이블, LS·대한·일진 ‘3자 분할’ 낙찰",
        "url": "https://www.electimes.com/news/articleView.html?idxno=368974",
        "source_name": "전기신문",
        "published_at": datetime(2026, 6, 11, 12, 0, tzinfo=KST),
        "seed": (
            "한국전력공사 상생조달처가 2026-06-09 ‘500kV 동해안~동서울 HVDC EP 2단계 지중송전사업’ "
            "케이블 구매 입찰을 마무리함. LS전선은 전력선 1공구, 대한전선은 전력선 2공구, "
            "일진전기는 중성선 3공구를 낙찰함. 사업 규모는 약 3,000억원대이며 동해안 발전력을 "
            "수도권으로 수송하는 국가 핵심 HVDC 전력망 사업임."
        ),
    },
    {
        "log_date": date(2026, 6, 17),
        "title": "대한전선, 1천463억 '500㎸ HVDC 동해안-동서울' 전력망 수주",
        "url": "https://www.yna.co.kr/view/AKR20260617045100003",
        "source_name": "연합뉴스",
        "published_at": datetime(2026, 6, 17, 9, 30, tzinfo=KST),
        "seed": (
            "대한전선은 2026-06-17 공시로 한국전력공사 ‘500kV HVDC 동해안∼동서울 건설공사"
            "(EP 2단계)’를 수주했다고 밝힘. 계약 규모는 부가세 포함 1,463억원이며, "
            "약 86km 규모 500kV HVDC XLPE 케이블 시스템을 제조·공급·시공(턴키)함. "
            "동해안 원자력·화력·재생에너지 전력을 수도권으로 공급하기 위한 국가 핵심 전력망임."
        ),
    },
    {
        "log_date": date(2026, 6, 17),
        "title": "대한전선, ‘500㎸ HVDC 동해안-동서울’ 건설공사 수주…1463억원 규모",
        "url": "https://biz.heraldcorp.com/article/10773310",
        "source_name": "헤럴드경제",
        "published_at": datetime(2026, 6, 17, 10, 0, tzinfo=KST),
        "seed": (
            "대한전선이 한전 500kV HVDC 동해안~동서울 건설공사(EP2단계)를 1,463억원에 수주함. "
            "500kV HVDC XLPE 케이블 제조·공급부터 시공까지 턴키로 수행하며, 약 86km 구간을 담당함. "
            "동해안 발전력을 수도권으로 수송하는 HVDC 국가 전력망 사업임."
        ),
    },
]


def _fallback_summary(item: dict, matched: list[str]) -> SummarizedArticle:
    """Fact-only summary when LLM is rate-limited."""
    seed = item["seed"]
    actor = "한국전력공사, LS전선, 대한전선, 일진전기"
    if "대한전선" in item["title"] and "분할" not in item["title"]:
        actor = "대한전선, 한국전력공사"
    return SummarizedArticle(
        title=item["title"],
        url=canonical_article_url(item["url"]),
        source_name=item["source_name"],
        category="korean",
        published_at=item["published_at"],
        matched_keywords=matched or ["HVDC"],
        llm_summary=seed,
        key_trends=["HVDC", "동해안-동서울 전력망"],
        ko_summary_steps=[
            f"투자 주체: {actor}",
            "투자 목적: 동해안 발전력을 수도권으로 안정 수송하기 위한 HVDC 전력망 구축",
            f"팩트 근거: {seed}",
            "위탁 연구 니즈: (의견) HVDC 케이블·변환·계통 연계 고난도 시험·실증",
            "접근 전략: (의견) 한전 EP 사업·서해안 에너지고속도로 로드맵과 정합",
        ],
        en_summary_steps=[],
        keyword_relevance=(
            "원문에서 HVDC(초고압 직류송전)·동해안~동서울 전력망이 직접 확인됨."
        ),
        ko_one_liner=seed[:180],
        rd_match_score=5,
        rd_proposable_area="HVDC 케이블·변환설비·계통 연계 시험·실증",
        rd_fact_basis=seed,
        rd_evidence_quotes=[],
    )


def main() -> int:
    settings = load_settings()
    store = DailyLogStore(settings.database_path)
    seen = {canonical_article_url(u) for u in store.get_seen_urls()}
    summarizer: Summarizer | None = None
    use_llm = os.getenv("BACKFILL_USE_LLM", "").lower() in ("1", "true", "yes")
    if use_llm:
        try:
            summarizer = Summarizer(settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Summarizer unavailable (%s) — using fact fallbacks", exc)
    else:
        logger.info("BACKFILL_USE_LLM not set — using fact-only fallbacks (no Groq)")

    by_date: dict[date, int] = {}
    for item in _ITEMS:
        url = canonical_article_url(item["url"])
        if url in seen:
            logger.info("Skip existing URL: %s", url)
            continue

        raw = RawArticle(
            title=item["title"],
            url=url,
            summary=item["seed"],
            source_name=item["source_name"],
            category="korean",
            published_at=item["published_at"],
        )
        enriched = enrich_raw_article(raw)
        domestic, _ = filter_domestic_articles([enriched], label="june-backfill")
        if not domestic:
            logger.warning("Dropped by korea_scope: %s", item["title"][:60])
            continue

        filtered = filter_articles(
            domestic,
            settings.keywords,
            required_keywords=settings.filter_keywords,
        )
        if not filtered:
            # Force keyword match — curated HVDC items.
            filtered = [
                FilteredArticle(
                    title=domestic[0].title,
                    url=domestic[0].url,
                    summary=domestic[0].summary,
                    source_name=domestic[0].source_name,
                    category=domestic[0].category,
                    published_at=domestic[0].published_at,
                    matched_keywords=["HVDC", "전력계통"],
                )
            ]
            logger.info("Forced keyword match for curated item: %s", item["title"][:50])

        article = filtered[0]
        summarized: SummarizedArticle | None = None
        if summarizer is not None:
            try:
                summarized = summarizer.summarize(article)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM summarize failed (%s) — fallback", exc)
        if summarized is None:
            summarized = _fallback_summary(item, article.matched_keywords)

        score = compute_rd_match_score(summarized, settings.analysis_keywords, monthly=True)
        if summarized.rd_match_score < score:
            summarized = replace(
                summarized,
                rd_match_score=max(summarized.rd_match_score, score),
            )

        inserted = store.save_entries(item["log_date"], [summarized])
        logger.info(
            "Inserted %d for %s: %s (score=%s)",
            inserted,
            item["log_date"],
            summarized.title[:50],
            summarized.rd_match_score,
        )
        if inserted:
            seen.add(url)
            by_date[item["log_date"]] = by_date.get(item["log_date"], 0) + inserted

    for log_date in sorted(by_date):
        result = rebuild_markdown_from_db(log_date, store, settings, repolish_db=True)
        logger.info("Daily rebuild: %s", result)

    logger.info("Done. dates=%s", {d.isoformat(): n for d, n in by_date.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
