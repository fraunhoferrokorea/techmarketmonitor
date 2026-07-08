"""Tests for executive-summary one-liner extraction (5W1H / ko_one_liner)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.daily_report import (
    _extract_fact_sentence,
    _informative_score,
    _is_interpretive_sentence,
    _is_vague,
)
from src.models import SummarizedArticle


def _article(**overrides) -> SummarizedArticle:
    base = dict(
        title="AI Startup Firmus to Build Indonesia Data Center With Nvidia",
        url="https://example.com/firmus",
        source_name="TechCrunch",
        category="tech_news",
        published_at=datetime(2026, 6, 28, 14, 1, tzinfo=timezone.utc),
        matched_keywords=["data center", "power grid"],
        llm_summary="Firmus partners with Nvidia. Source: https://example.com/firmus",
        key_trends=["data center expansion"],
        ko_summary_steps=[
            "**개요:** 오스트레일리아 AI 인프라 Firmus Technologies가 Nvidia와 협력해 인도네시아에 첫 데이터센터를 건설할 예정임.",
            "**핵심 내용:** Firmus는 인도네시아에서 첫 데이터센터를 건설하기 위해 Nvidia와 파트너십을 맺었음.",
            "**시장 파급력:** 이 프로젝트는 Firmus에 2032년까지 약 $30억의 수주 계약을 유도할 것으로 예상됨.",
        ],
        en_summary_steps=[],
        keyword_relevance="",
        ko_one_liner="",
    )
    base.update(overrides)
    return SummarizedArticle(**base)


def test_ko_one_liner_preferred_over_steps():
    article = _article(
        ko_one_liner=(
            "오스트레일리아 AI 인프라 Firmus Technologies가 Nvidia와 협력해 "
            "인도네시아에 첫 데이터센터를 건설하며, 6년간 최대 $300억 규모 "
            "수주(offtake) 계약을 유치할 전망임."
        ),
    )
    fact = _extract_fact_sentence(article, ["전력계통"], "indirect")
    assert "$300억" in fact or "$30" in fact
    assert "Firmus" in fact
    assert "인도네시아" in fact


def test_fallback_prefers_quantitative_sentence():
    article = _article()
    fact = _extract_fact_sentence(article, ["전력계통"], "indirect")
    assert "$30억" in fact or "2032" in fact
    assert "파트너십을 맺었음" not in fact


def test_vague_reaction_sentence_rejected():
    assert _is_vague("엘론 머스크의 궤도 데이터 센터 비전은 다양한 산업 리더들의 의문을 불러일으켰음.")


def test_informative_score_ranks_quant_higher():
    vague = "Firmus는 인도네시아에서 첫 데이터센터를 건설하기 위해 Nvidia와 파트너십을 맺었음."
    rich = "Firmus Technologies는 Nvidia와 협력해 인도네시아에 데이터센터를 건설하며 2032년까지 $30억 수주를 유치할 전망임."
    assert _informative_score(rich) > _informative_score(vague)


def test_interpretive_sentence_rejected_for_core_issue():
    assert _is_interpretive_sentence("중소기업 지원 흐름과 연결되는 시장 신호로 보임.")
    article = _article(
        ko_one_liner="정부의 해상풍력 보급 목표와 연계, 한국서부발전의 석탄화력 발전소 폐쇄 계획과 활용함.",
        ko_summary_steps=[
            "**개요:** 기후에너지환경부와 한국서부발전은 2030년 준공 목표로 500MW 태안해상풍력을 추진함.",
            "**접근 전략:** 정부의 해상풍력 보급 목표와 연계함.",
        ],
    )
    fact = _extract_fact_sentence(article, ["전력계통"], "direct")
    assert "500MW" in fact
    assert "연계" not in fact
