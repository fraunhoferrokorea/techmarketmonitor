from __future__ import annotations

from datetime import datetime, timezone

from src.models import SummarizedArticle
from src.rd_targeting import (
    build_rd_targeting_block,
    compute_rd_match_score,
    has_investment_signal,
    is_domestic_rd_target,
    is_excluded_rd_news,
    is_non_rd_program_news,
    is_research_outcome_without_investment_signal,
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


def test_compute_rd_match_score_keyword_adjustment() -> None:
    from src.rd_targeting import compute_rd_match_score

    grid_kws = ["전력계통", "스마트그리드", "파워그리드"]
    assert compute_rd_match_score(_article(), grid_kws) >= 4

    off_topic = _article(
        title="응급환자 이송체계 혁신 시범사업",
        matched_keywords=[],
        ko_summary_steps=[
            "**개요:** 보건복지부와 소방청이 응급환자 이송체계 시범사업을 추진함.",
            "**투자 주체:** 보건복지부, 소방청",
            "**투자 목적:** 응급의료 전달체계 개편",
            "**위탁 연구 니즈:** 팩트 부족으로 판단 보류",
            "**접근 전략:** 정책 정합성 검토",
        ],
        rd_proposable_area="응급의료 전달체계 개편 관련 기술개발",
        rd_match_score=3,
    )
    assert compute_rd_match_score(off_topic, grid_kws) <= 2


def test_non_rd_student_field_trip_excluded() -> None:
    article = _article(
        title="제주·경남 대학생 45명 에너지 산업현장으로",
        llm_summary=(
            "제주대·경상국립대·창원대 학생 45명이 2026 제주-경남 협력형 "
            "비교과 프로그램에 참여해 에너지 산업현장으로 현장교육을 받았음."
        ),
        rd_match_score=3,
        rd_proposable_area="에너지 기술 및 전력계통 분야의 산업 현장 적용 연구",
        ko_summary_steps=[
            "**개요:** 제주·경남 대학생 45명이 에너지 산업현장으로 현장교육을 받았음.",
            "**투자 주체:** 제주대학교, 경상국립대학교, 국립창원대학교",
            "**투자 목적:** 해당 없음",
            "**위탁 연구 니즈:** 팩트 부족으로 판단 보류",
            "**접근 전략:** 해당 없음",
        ],
    )
    grid_kws = ["전력계통", "스마트그리드", "파워그리드"]

    assert is_non_rd_program_news(article)
    assert compute_rd_match_score(article, grid_kws) == 0
    assert build_rd_targeting_block(article, grid_kws) == []


def test_industrial_demonstration_not_excluded() -> None:
    article = _article(
        title="산업현장 실증 사업 본격 추진",
        llm_summary="한국전력과 참여기업이 산업현장 실증 과제를 수행함.",
        ko_summary_steps=[
            "**개요:** 산업현장 실증 과제가 착수됨.",
            "**투자 주체:** 한국전력공사",
            "**투자 목적:** 기술 고도화",
            "**위탁 연구 니즈:** 실증 기술 격차",
            "**접근 전략:** 정책 정합",
        ],
    )
    assert not is_non_rd_program_news(article)


def test_epidemiology_meta_analysis_excluded_from_rd_scoring() -> None:
    article = _article(
        title='"자동차 매연, 소아암 최악" 암 위험 최대 68%↑',
        source_name="연합뉴스",
        llm_summary=(
            "이화여대·국립암센터·미네소타대 연구팀이 교통 대기오염과 소아암 "
            "상관관계 메타분석 결과를 발표함."
        ),
        rd_match_score=3,
        rd_proposable_area="대기오염 저감 기술 개발",
        ko_summary_steps=[
            "**개요:** 교통 대기오염과 소아암 상관관계 메타분석 결과가 발표됨.",
            "**투자 주체:** 명시 없음",
            "**투자 목적:** 해당 없음",
            "**위탁 연구 니즈:** 팩트 부족으로 판단 보류",
            "**접근 전략:** 해당 없음",
        ],
    )
    grid_kws = ["전력계통", "스마트그리드", "파워그리드"]

    assert is_research_outcome_without_investment_signal(article)
    assert is_excluded_rd_news(article)
    assert compute_rd_match_score(article, grid_kws) == 0
    assert build_rd_targeting_block(article, grid_kws) == []


def test_research_outcome_with_budget_not_excluded() -> None:
    article = _article(
        title="환경부, 대기오염 저감 R&D 500억 예산 편성",
        llm_summary="환경부가 대기오염 저감 기술 개발 지원 사업 예산을 편성함.",
        ko_summary_steps=[
            "**개요:** 환경부가 대기오염 저감 R&D 예산을 편성함.",
            "**투자 주체:** 환경부",
            "**투자 목적:** 저감 기술 개발",
            "**위탁 연구 니즈:** 고난도 저감 기술 격차",
            "**접근 전략:** 정책 정합",
        ],
    )
    assert not is_research_outcome_without_investment_signal(article)
    assert not is_excluded_rd_news(article)
