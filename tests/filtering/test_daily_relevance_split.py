"""Tests for daily report relevance split (primary vs low-relevance appendix)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from src.daily_report import _build_markdown, classify_keyword_relevance
from src.models import SummarizedArticle


def _article(
    title: str,
    matched: list[str],
    *,
    url_suffix: str = "a",
    **overrides,
) -> SummarizedArticle:
    base = dict(
        title=title,
        url=f"https://example.com/{url_suffix}",
        source_name="산업통상부 보도자료",
        category="korean",
        published_at=datetime(2026, 7, 9, 1, 0, tzinfo=timezone.utc),
        matched_keywords=matched,
        llm_summary="요약. 출처: https://example.com",
        key_trends=[],
        ko_summary_steps=[f"**개요:** {title}"],
        en_summary_steps=[],
        keyword_relevance="",
        ko_one_liner=title,
        rd_match_score=1,
        rd_proposable_area="해당 없음",
        rd_fact_basis="명시 없음",
    )
    base.update(overrides)
    return SummarizedArticle(**base)


def test_korean_power_matched_keyword_is_direct() -> None:
    article = _article("한전, 전력계통 안정화 사업 추진", ["전력계통", "투자"])
    assert classify_keyword_relevance(article, ["전력계통", "스마트그리드", "파워그리드"]) == "direct"


def test_llm_invented_grid_text_does_not_inflate_relevance() -> None:
    article = _article(
        "대법원, 청사 공간 확보 계획",
        ["투자"],
        url_suffix="court",
        ko_summary_steps=[
            "**개요:** 대법원이 청사 공간을 확보함.",
            "**위탁 연구 니즈:** 스마트그리드 기술 개발",
        ],
        keyword_relevance="스마트그리드·전력계통과 연계 가능",
    )
    assert classify_keyword_relevance(article, ["전력계통", "스마트그리드", "파워그리드"]) == "weak"


def test_daily_markdown_moves_weak_items_to_appendix() -> None:
    kws = ["전력계통", "스마트그리드", "파워그리드"]
    primary = _article("과기정통부, 스마트그리드 R&D 공고", ["스마트그리드"], url_suffix="grid")
    weak = _article("중소기업 퇴직연금 업무협약", ["MOU", "투자"], url_suffix="pension")
    md = _build_markdown(date(2026, 7, 9), [primary, weak], kws, recorder="test")

    assert "## 관련도 낮음 (참고)" in md
    assert "퇴직연금" in md
    assert "R&D 공고" in md
    assert "관련도 낮음 1건은 참고 섹션" in md
    main_body = md.split("## 관련도 낮음")[0]
    assert "퇴직연금" not in main_body
