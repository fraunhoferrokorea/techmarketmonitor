"""Tests for inline keyword highlighting in daily reports."""
from __future__ import annotations

from datetime import datetime, timezone

from src.daily_report import (
    _highlight_after_md_label,
    _highlight_keywords,
    _keywords_for_highlight,
    strip_keyword_marks,
)
from src.models import SummarizedArticle
from src.policy_priority import gov_target_pass_label


def _article(**overrides) -> SummarizedArticle:
    base = dict(
        title="한전 스마트그리드 실증 착수",
        url="https://example.com/sg",
        source_name="정책브리핑",
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
