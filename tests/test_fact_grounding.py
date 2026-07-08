from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fact_grounding import (
    audit_summarized_fields,
    is_analyst_commentary,
    sanitize_summarized_article,
)
from src.models import FilteredArticle, SummarizedArticle
from src.rd_targeting import parse_rd_fields


def _filtered(**overrides) -> FilteredArticle:
    base = dict(
        title='NH증권 "LG엔솔, ESS 병목이 단기 실적 발목…목표가↓"',
        url="https://www.yna.co.kr/view/AKR20260708030000008",
        summary=(
            "NH투자증권은 8일 LG에너지솔루션에 대해 에너지저장장치(ESS) 병목이 단기 실적의 "
            "발목을 잡고 있다며 목표주가를 기존 58만원에서 48만원으로 하향 조정했다. "
            "주민우 연구원은 미국 ESS 팩 병목이 단기 실적에 미치는 부정적 영향이 기존 예상보다 "
            "크다며 할인율을 10%포인트 상향한다고 밝혔다."
        ),
        source_name="연합뉴스 경제",
        category="korean",
        published_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        matched_keywords=["에너지저장", "투자"],
    )
    base.update(overrides)
    return FilteredArticle(**base)


def _hallucinated_summary(**overrides) -> SummarizedArticle:
    base = dict(
        title='NH증권 "LG엔솔, ESS 병목이 단기 실적 발목…목표가↓"',
        url="https://www.yna.co.kr/view/AKR20260708030000008",
        source_name="연합뉴스 경제",
        category="korean",
        published_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        matched_keywords=["에너지저장", "투자"],
        llm_summary="NH증권 ESS 분석. 출처: https://www.yna.co.kr/view/AKR20260708030000008",
        key_trends=["ESS"],
        ko_summary_steps=[
            "**개요:** NH증권은 LG에너지솔루션의 ESS 병목이 단기 실적에 영향을 미칠 것으로 분석함.",
            "**투자 주체:** NH투자증권",
            "**투자 목적:** 에너지저장장치(ESS) 기술 개발 및 투자 분석",
            "**위탁 연구 니즈:** 에너지저장장치(ESS) 기술 개발 및 스마트그리드 연계 연구",
            "**접근 전략:** 에너지저장장치(ESS) 기술 개발 및 스마트그리드 연계 연구를 통해 전력계통 안정성 향상을 도모할 수 있음",
        ],
        en_summary_steps=[],
        keyword_relevance="스마트그리드 연계 R&D 제안 기회",
        ko_one_liner=(
            "NH증권은 LG에너지솔루션의 에너지저장장치(ESS) 병목이 단기 실적에 영향을 미칠 것으로 "
            "분석하고, 에너지저장장치(ESS) 기술 개발 및 스마트그리드 연계 연구를 제안함."
        ),
        rd_match_score=2,
        rd_proposable_area="에너지저장장치(ESS) 기술 개발 및 스마트그리드 연계 연구",
        rd_fact_basis="LG에너지솔루션의 에너지저장장치(ESS) 병목 현상",
    )
    base.update(overrides)
    return SummarizedArticle(**base)


def test_detects_analyst_report_source() -> None:
    source = _filtered()
    assert is_analyst_commentary(source.summary)


def test_flags_smart_grid_hallucination() -> None:
    source = _filtered()
    summary = _hallucinated_summary()
    issues = audit_summarized_fields(source, summary)
    fields = {issue.field for issue in issues}
    assert "rd_proposable_area" in fields
    assert any("스마트그리드" in issue.detail for issue in issues)


def test_sanitize_nh_report_removes_fabricated_rd_proposal() -> None:
    source = _filtered()
    cleaned = sanitize_summarized_article(source, _hallucinated_summary())

    assert cleaned.rd_proposable_area == "해당 없음"
    assert "스마트그리드" not in cleaned.ko_one_liner
    assert "제안" not in cleaned.ko_one_liner
    assert "기술 개발" not in cleaned.ko_one_liner
    assert "스마트그리드" not in " ".join(cleaned.ko_summary_steps)
    assert cleaned.rd_match_score <= 2

    fields = parse_rd_fields(cleaned.ko_summary_steps)
    assert fields["pain_point"] == "팩트 부족으로 판단 보류"
    assert fields["approach_strategy"] == "해당 없음"


def test_grounded_government_rd_passes_through() -> None:
    source = FilteredArticle(
        title="과기정통부, 스마트그리드 R&D 5000억 투자 계획 발표",
        url="https://example.com/msit",
        summary="과기정통부(MSIT)가 2027–2031 스마트그리드 R&D에 5000억원을 투입할 계획임.",
        source_name="과기정통부",
        category="korean",
        published_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
        matched_keywords=["스마트그리드"],
    )
    summary = SummarizedArticle(
        title=source.title,
        url=source.url,
        source_name=source.source_name,
        category=source.category,
        published_at=source.published_at,
        matched_keywords=source.matched_keywords,
        llm_summary="MSIT plan. 출처: https://example.com/msit",
        key_trends=["grid R&D"],
        ko_summary_steps=[
            "**개요:** 과기정통부(MSIT)가 2027–2031 스마트그리드 R&D에 5000억원 투자 계획을 발표함.",
            "**투자 주체:** 과학기술정보통신부(MSIT)",
            "**투자 목적:** 스마트그리드 R&D 고도화",
            "**위탁 연구 니즈:** 고난도 계통 실증 기술 격차",
            "**접근 전략:** MSIT 디지털·에너지 R&D 정책과 정합",
        ],
        rd_match_score=4,
        rd_proposable_area="스마트그리드 R&D 실증·계통 연동",
        rd_fact_basis="2027–2031 5000억원 R&D 투입",
        ko_one_liner="과기정통부(MSIT)가 2027–2031 스마트그리드 R&D에 5000억원을 투입할 계획임.",
    )
    cleaned = sanitize_summarized_article(source, summary)
    assert cleaned.rd_proposable_area == summary.rd_proposable_area
    assert cleaned.ko_one_liner == summary.ko_one_liner
