from __future__ import annotations

from datetime import datetime, timezone

from src.daily_report import _credibility, credibility_legend_lines
from src.models import SummarizedArticle


def _article(**overrides) -> SummarizedArticle:
    base = dict(
        title="테스트",
        url="https://example.com",
        source_name="출처",
        category="korean",
        published_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
        matched_keywords=[],
        llm_summary="",
        key_trends=[],
        ko_summary_steps=[],
        en_summary_steps=[],
    )
    base.update(overrides)
    return SummarizedArticle(**base)


def test_credibility_government_press_release_is_a() -> None:
    article = _article(
        source_name="과기정통부 보도자료",
        url="https://www.msit.go.kr/bbs/view.do?sCode=user&mId=113&mPid=112&pageIndex=&bbsSeqNo=94&nttSeqNo=1",
    )
    assert _credibility(article) == "A"


def test_credibility_yonhap_is_a() -> None:
    article = _article(
        source_name="연합뉴스 경제",
        url="https://www.yna.co.kr/view/AKR20260621000100003",
    )
    assert _credibility(article) == "A"


def test_credibility_domestic_media_is_b() -> None:
    article = _article(
        source_name="헤럴드경제",
        url="https://biz.heraldcorp.com/article/1",
    )
    assert _credibility(article) == "B"


def test_credibility_legend_mentions_korea_sources() -> None:
    legend = "\n".join(credibility_legend_lines())
    assert ".go.kr" in legend
    assert "전기신문" in legend or "매일경제" in legend
    assert "Reuters" not in legend
    assert "arXiv" not in legend
