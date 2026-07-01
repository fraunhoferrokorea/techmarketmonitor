"""Tests for Korea-only article scope filter."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.filter import filter_articles
from src.korea_scope import is_domestic_news, is_foreign_url, is_korea_scoped
from src.models import RawArticle


def _article(
    title: str,
    summary: str = "",
    *,
    url: str = "https://www.yna.co.kr/news/example",
    category: str = "korean",
    source: str = "연합뉴스",
) -> RawArticle:
    return RawArticle(
        title=title,
        url=url,
        summary=summary,
        source_name=source,
        category=category,
        published_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )


def test_foreign_url_blocked() -> None:
    assert is_foreign_url("https://arxiv.org/abs/2606.27712")
    assert is_foreign_url("https://electrek.co/2026/06/30/example")
    assert is_foreign_url("https://www.bloomberg.com/news/example")
    assert not is_foreign_url("https://www.msit.go.kr/news/1")


def test_electrek_story_excluded() -> None:
    article = _article(
        "$383 million port grant to create 22,000 clean jobs",
        "Long Beach port infrastructure grant.",
        url="https://electrek.co/2026/06/30/grant",
        source="Electrek",
    )
    assert not is_korea_scoped(article)
    assert not is_domestic_news(article)


def test_bloomberg_story_excluded() -> None:
    article = _article(
        "Bitcoin Miners Valuable Asset for Electric Grid",
        "US miners pivot to AI data centers.",
        url="https://www.bloomberg.com/news/videos/example",
        source="Bloomberg Technology",
    )
    assert not is_korea_scoped(article)


def test_us_only_story_excluded() -> None:
    article = _article(
        "AI fuels record $200bn M&A boom in US power sector",
        "US utilities merge to meet data center demand.",
    )
    assert not is_korea_scoped(article)


def test_korean_domestic_story_included() -> None:
    article = _article(
        "농협은행, 전남 광양 BESS 2천억 자금 조달 주선",
        "국내 신재생에너지 저장 사업에 NH농협은행이 참여함.",
    )
    assert is_korea_scoped(article)


def test_korean_company_domestic_plan_included() -> None:
    article = _article(
        "South Korea Unveils Plan to Sustain Lead in AI",
        "Samsung and SK hynix plan 13 trillion won domestic investment.",
    )
    assert is_korea_scoped(article)


def test_newsis_domestic_included() -> None:
    article = _article(
        '만호제강 "1000억 규모 비영업자산 매각 추진"',
        "만호제강이 국내 자산 매각을 추진함.",
        url="https://www.newsis.com/view/NISX20260701_0003690595",
        source="뉴시스 속보",
    )
    assert is_domestic_news(article)


def test_filter_articles_drops_foreign_only() -> None:
    articles = [
        _article("美 전력 M&A 사상 최대", "미국 전력업계 거래 급증"),
        _article("한국, 스마트그리드 R&D 5000억 투자", "과기정통부가 국내 계획 발표"),
        _article(
            "SpaceX Cuts Starlink Prices in Memphis",
            "US data center opposition.",
            url="https://www.bloomberg.com/news/articles/example",
            source="Bloomberg Technology",
        ),
    ]
    matched = filter_articles(articles, ["스마트그리드", "전력계통"])
    assert len(matched) == 1
    assert "한국" in matched[0].title


if __name__ == "__main__":
    test_foreign_url_blocked()
    test_electrek_story_excluded()
    test_bloomberg_story_excluded()
    test_us_only_story_excluded()
    test_korean_domestic_story_included()
    test_korean_company_domestic_plan_included()
    test_newsis_domestic_included()
    test_filter_articles_drops_foreign_only()
    print("ok")
