"""Preview monthly R&D candidates from configured ministry/agency sources (no LLM)."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_settings, load_sources
from src.daily_report import classify_keyword_relevance
from src.fetchers.html_boards import fetch_html_boards_for_date
from src.fetchers.pacst import fetch_pacst_for_date
from src.fetchers.registry import build_fetchers
from src.filter import filter_articles
from src.models import SummarizedArticle
from src.rd_targeting import MONTHLY_RD_MIN_SCORE, compute_rd_match_score

KST = ZoneInfo("Asia/Seoul")


def _pub_date(article) -> date | None:
    if article.published_at is None:
        return None
    pub = article.published_at
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    return pub.astimezone(KST).date()


def _to_summarized(article, top_kw: list[str]) -> SummarizedArticle:
    base = SummarizedArticle(
        title=article.title,
        url=article.url,
        source_name=article.source_name,
        category=article.category,
        published_at=article.published_at,
        matched_keywords=article.matched_keywords,
        llm_summary=article.summary or "",
        key_trends=[],
        ko_summary_steps=[],
        en_summary_steps=[],
        keyword_relevance="",
        ko_one_liner=(article.summary or article.title)[:200],
        rd_match_score=0,
        rd_proposable_area="",
        rd_fact_basis="",
    )
    relevance = classify_keyword_relevance(base, top_kw)
    return SummarizedArticle(
        title=base.title,
        url=base.url,
        source_name=base.source_name,
        category=base.category,
        published_at=base.published_at,
        matched_keywords=base.matched_keywords,
        llm_summary=base.llm_summary,
        key_trends=base.key_trends,
        ko_summary_steps=base.ko_summary_steps,
        en_summary_steps=base.en_summary_steps,
        keyword_relevance=relevance,
        ko_one_liner=base.ko_one_liner,
        rd_match_score=base.rd_match_score,
        rd_proposable_area=base.rd_proposable_area,
        rd_fact_basis=base.rd_fact_basis,
    )


def main() -> None:
    settings = load_settings()
    top_kw = settings.analysis_keywords
    start = date(2026, 6, 1)
    end = date(2026, 6, 29)

    rss_raw = []
    for fetcher in build_fetchers(load_sources(), settings.keywords):
        try:
            rss_raw.extend(fetcher.fetch())
        except Exception:
            pass

    candidates: list[tuple[date, int, str, str, str]] = []
    cursor = start
    while cursor <= end:
        raw = list(fetch_html_boards_for_date(cursor))
        raw.extend(fetch_pacst_for_date(cursor))
        seen = {a.url for a in raw}
        for article in rss_raw:
            if _pub_date(article) == cursor and article.url not in seen:
                raw.append(article)
                seen.add(article.url)

        for art in filter_articles(
            raw, settings.keywords, required_keywords=settings.filter_keywords
        ):
            sa = _to_summarized(art, top_kw)
            score = compute_rd_match_score(sa, top_kw)
            if score >= MONTHLY_RD_MIN_SCORE:
                candidates.append(
                    (
                        cursor,
                        score,
                        sa.keyword_relevance or "",
                        art.source_name,
                        art.title,
                    )
                )
        cursor += timedelta(days=1)

    candidates.sort(key=lambda x: (-x[1], x[0].isoformat()))

    print(f"=== Heuristic monthly candidates {start}..{end} (score>={MONTHLY_RD_MIN_SCORE}) ===")
    print(f"Total: {len(candidates)} (ministry/agency press releases only)")
    print()
    for d, score, rel, src, title in candidates[:50]:
        print(f"{d} | {score}/5 | {rel:6s} | {src} | {title[:70]}")
    if len(candidates) > 50:
        print(f"... and {len(candidates) - 50} more")


if __name__ == "__main__":
    main()
