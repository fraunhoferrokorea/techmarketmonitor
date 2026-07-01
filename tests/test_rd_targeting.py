from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import SummarizedArticle
from src.rd_targeting import (
    build_rd_targeting_block,
    has_investment_signal,
    is_domestic_rd_target,
    parse_rd_fields,
)


def _article(**overrides) -> SummarizedArticle:
    base = dict(
        title="과기정통부, 스마트그리드 R&D 5000억 투자 계획 발표",
        url="https://example.com/msit",
        source_name="과기정통부",
        category="korean",
        published_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
        matched_keywords=["스마트그리드"],
        llm_summary="MSIT announces plan. 출처: https://example.com/msit",
        key_trends=["grid R&D"],
        ko_summary_steps=[
            "**개요:** 과기정통부(MSIT)가 2027–2031 스마트그리드 R&D에 5000억원 투자 계획을 발표함.",
            "**투자 주체:** 과학기술정보통신부(MSIT), 한국전력공사(KEPCO)",
            "**투자 목적:** 계통 안정성 고도화 및 국산 EMS 기술 내재화",
            "**위탁 연구 니즈:** 고난도 계통 시뮬레이션·실증 기술은 국내 TRL 4 수준으로 시간 제약 존재",
            "**접근 전략:** MSIT 디지털·에너지 R&D 정책 목표와 Fraunhofer 계통 실증 역량 정합성 강조",
        ],
        en_summary_steps=[],
        keyword_relevance="",
        ko_one_liner="",
    )
    base.update(overrides)
    return SummarizedArticle(**base)


def test_has_investment_signal_detects_budget_keywords() -> None:
    article = _article()
    assert has_investment_signal(article)


def test_parse_rd_fields_from_ko_steps() -> None:
    fields = parse_rd_fields(_article().ko_summary_steps)
    assert "MSIT" in fields["investment_actor"]
    assert "내재화" in fields["investment_purpose"]
    assert "TRL" in fields["pain_point"]


def test_is_domestic_rd_target() -> None:
    fields = parse_rd_fields(_article().ko_summary_steps)
    assert is_domestic_rd_target(fields["investment_actor"])
    assert not is_domestic_rd_target("국내 주체: 해당 없음(해외)")


def test_build_rd_targeting_block_renders_markdown() -> None:
    lines = build_rd_targeting_block(_article())
    assert any("R&D 타겟팅" in line for line in lines)
    assert any("R&D 적합도" in line for line in lines)
    assert any("투자 주체" in line for line in lines)


def test_compute_rd_match_score_heuristic() -> None:
    from src.rd_targeting import compute_rd_match_score

    score = compute_rd_match_score(_article())
    assert score >= 3


if __name__ == "__main__":
    test_has_investment_signal_detects_budget_keywords()
    test_parse_rd_fields_from_ko_steps()
    test_is_domestic_rd_target()
    test_build_rd_targeting_block_renders_markdown()
    test_compute_rd_match_score_heuristic()
    print("ok")
