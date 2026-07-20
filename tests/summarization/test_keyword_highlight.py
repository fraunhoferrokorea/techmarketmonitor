"""Tests for inline keyword highlighting in daily reports."""
from __future__ import annotations

from datetime import datetime, timezone

from src.daily_report import (
    _highlight_after_md_label,
    _highlight_keywords,
    _keywords_for_highlight,
    format_monitoring_keyword_header,
    strip_keyword_marks,
)
from src.models import SummarizedArticle
from src.policy_priority import gov_target_pass_label


def _article(**overrides) -> SummarizedArticle:
    base = dict(
        title="한전 스마트그리드 실증 착수",
        url="https://example.com/sg",
        source_name="산업통상부 보도자료",
        category="tech_news",
        published_at=datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc),
        matched_keywords=["스마트그리드", "전력망"],
        llm_summary="한전이 스마트그리드 실증에 착수함.",
        key_trends=[],
        ko_summary_steps=[],
        en_summary_steps=[],
        keyword_relevance="",
        ko_one_liner="",
    )
    base.update(overrides)
    return SummarizedArticle(**base)


def test_highlight_wraps_matched_terms():
    text = "한전이 스마트그리드와 전력망 현대화를 추진함."
    result = _highlight_keywords(text, ["스마트그리드", "전력망"])
    assert "<mark>스마트그리드</mark>" in result
    assert "<mark>전력망</mark>" in result


def test_highlight_is_case_insensitive_for_ascii():
    result = _highlight_keywords("BESS and bess storage", ["BESS"])
    assert result.count("<mark>") == 2
    assert "<mark>BESS</mark>" in result
    assert "<mark>bess</mark>" in result


def test_highlight_skips_urls_and_existing_marks():
    text = "详见 https://example.com/스마트그리드 및 <mark>전력망</mark> 참고"
    result = _highlight_keywords(text, ["스마트그리드", "전력망"])
    assert "https://example.com/스마트그리드" in result
    assert result.count("<mark>전력망</mark>") == 1


def test_highlight_prefers_longer_keyword():
    result = _highlight_keywords("스마트그리드 구축", ["스마트", "스마트그리드"])
    assert "<mark>스마트그리드</mark>" in result
    assert "<mark>스마트</mark>" not in result


def test_highlight_after_label_leaves_heading_alone():
    line = "- **제안 R&D 영역:** 에너지저장 및 전력망 현대화"
    result = _highlight_after_md_label(line, ["R&D", "에너지저장", "전력망"])
    assert result.startswith("- **제안 R&D 영역:**")
    assert "<mark>에너지저장</mark>" in result
    assert "<mark>전력망</mark>" in result
    assert "<mark>R&D</mark>" not in result


def test_keywords_for_highlight_skips_gov_label():
    article = _article(
        matched_keywords=[gov_target_pass_label(), "스마트그리드"],
    )
    kws = _keywords_for_highlight(article, ["전력계통", "스마트그리드"])
    assert gov_target_pass_label() not in kws
    assert kws[0] == "스마트그리드" or "스마트그리드" in kws
    assert "전력계통" in kws


def test_strip_keyword_marks():
    assert strip_keyword_marks("한전 <mark>스마트그리드</mark> 실증") == "한전 스마트그리드 실증"


def test_monthly_markdown_highlights_keywords():
    from src.rd_monthly_report import _build_markdown

    kws = ["전력계통", "스마트그리드", "파워그리드"]
    compact = [
        {
            "ref": 1,
            "date": "2026-07-01",
            "title": "한전 스마트그리드 실증",
            "url": "https://example.com/sg",
            "source": "산업통상부 보도자료",
            "score": 4,
            "relevance": "직접",
            "matched_keywords": "스마트그리드, 전력계통",
            "actor": "한전",
            "purpose": "전력계통 현대화",
            "pain": "스마트그리드 실증 역량",
            "strategy": "공동연구",
            "proposable": "파워그리드 분석",
            "fact": "스마트그리드 예산 발표",
            "keyword_relevance": "",
            "summary": "한전이 스마트그리드와 전력계통 실증에 착수함.",
        }
    ]
    structured = {
        "executive_summary": "당월 스마트그리드·전력계통 R&D 신호가 확인됨.",
        "context_highlights": [
            {
                "relevance": "직접",
                "matched_keywords": "스마트그리드, 전력계통",
                "summary": "스마트그리드 실증이 확대됨.",
                "refs": [1],
            }
        ],
        "opportunities": [
            {
                "field": "전력·그리드",
                "summary": "스마트그리드 관련 위탁 수요가 있음.",
                "items": ["한전이 파워그리드 분석을 추진함."],
                "refs": [1],
            }
        ],
        "action_plan": [
            {
                "target": "한전",
                "rd_area": "스마트그리드 실증",
                "contact_angle": "전력계통 공동연구",
            }
        ],
    }
    md = _build_markdown(2026, 7, [{"id": 1}], compact, structured, kws)

    assert (
        "**모니터링 키워드:** <mark>전력계통</mark> · <mark>스마트그리드</mark> · <mark>파워그리드</mark>"
        in md
    )
    assert "<mark>스마트그리드</mark>" in md
    assert "<mark>전력계통</mark>" in md
    assert "<mark>파워그리드</mark>" in md
    assert "매칭: <mark>스마트그리드</mark>, <mark>전력계통</mark>" in md


def test_format_monitoring_keyword_header_top5_with_deung() -> None:
    kws = [
        "전력계통",
        "스마트그리드",
        "파워그리드",
        "에너지고속도로",
        "AI 기반 전력계통 운영",
        "DC Grid",
        "재생에너지 출력예측",
    ]
    assert format_monitoring_keyword_header(kws) == (
        "<mark>전력계통</mark> · <mark>스마트그리드</mark> · <mark>파워그리드</mark> · "
        "<mark>에너지고속도로</mark> · <mark>AI 기반 전력계통 운영</mark> 등"
    )
    assert format_monitoring_keyword_header(kws, mark=False) == (
        "전력계통 · 스마트그리드 · 파워그리드 · 에너지고속도로 · AI 기반 전력계통 운영 등"
    )
    assert format_monitoring_keyword_header(kws[:3]) == (
        "<mark>전력계통</mark> · <mark>스마트그리드</mark> · <mark>파워그리드</mark>"
    )
    assert format_monitoring_keyword_header([]) == "(미설정)"
