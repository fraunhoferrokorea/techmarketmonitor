from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
        source_name="정책브리핑 과기정통부",
        url="https://www.korea.kr/briefing/pressReleaseView.do?newsId=1",
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
    assert "korea.kr" in legend
    assert "Reuters" not in legend
    assert "arXiv" not in legend


if __name__ == "__main__":
    test_credibility_government_press_release_is_a()
    test_credibility_yonhap_is_a()
    test_credibility_domestic_media_is_b()
    test_credibility_legend_mentions_korea_sources()
    print("ok")
