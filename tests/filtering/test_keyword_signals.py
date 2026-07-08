"""Tests for executive-summary keyword connection lines (not fact duplicates)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.daily_report import _exec_summary_item, _keyword_connection
from src.models import SummarizedArticle


def _article(title: str, matched: list[str], **overrides) -> SummarizedArticle:
    base = dict(
        title=title,
        url=f"https://example.com/{hash(title) % 10_000}",
        source_name="TechCrunch",
        category="tech_news",
        published_at=datetime(2026, 6, 28, 14, 1, tzinfo=timezone.utc),
        matched_keywords=matched,
        llm_summary="Summary. Source: https://example.com",
        key_trends=[],
        ko_summary_steps=[
            f"**개요:** {title} 관련 내용임.",
            "**핵심:** 2032년까지 $30억 규모 프로젝트로 예상됨.",
        ],
        en_summary_steps=[],
        keyword_relevance="",
        ko_one_liner="",
    )
    base.update(overrides)
    return SummarizedArticle(**base)


def test_indirect_connection_explains_classification_not_facts():
    kws = ["전력계통", "파워그리드", "스마트그리드"]
    article = _article(
        "AI Startup Firmus to Build Indonesia Data Center With Nvidia",
        ["data center"],
    )
    row = _exec_summary_item(article, kws)
    assert row is not None
    _fact, level_label, connection = row
    assert level_label == "간접"
    assert "간접 연관" in connection
    assert "전력계통" in connection
    assert "1차 주제" in connection
    assert "Firmus" not in connection
    assert "$30억" not in connection
    assert "…" not in connection
    assert "..." not in connection


def test_direct_connection_explains_keyword_link():
    kws = ["전력계통", "파워그리드", "스마트그리드"]
    article = _article(
        "What Europe's heat wave means for the power grid",
        ["power grid"],
        ko_one_liner=(
            "유럽 폭염이 전력계통에 부담을 주며 향후 전기 수요 30% 증가가 예상됨."
        ),
    )
    row = _exec_summary_item(article, kws)
    assert row is not None
    connection = row[2]
    assert "직접 연관" in connection
    assert "30%" not in connection
    assert "폭염" not in connection


def test_keyword_connection_direct_level():
    kws = ["전력계통", "파워그리드", "스마트그리드"]
    article = _article("Grid stability report", ["power grid"])
    line = _keyword_connection(article, kws, "direct")
    assert "직접 연관" in line
    assert "→" not in line
