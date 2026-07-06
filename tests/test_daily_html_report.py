from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.daily_html_report import build_daily_html
from src.daily_report import save_daily_report
from src.models import SummarizedArticle


def _article(**overrides) -> SummarizedArticle:
    base = dict(
        title="직류 산업 확산 추진",
        url="https://www.korea.kr/briefing/pressReleaseView.do?newsId=1",
        source_name="정책브리핑 기후에너지환경부",
        category="korean",
        published_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
        matched_keywords=["power grid", "smart grid"],
        llm_summary="",
        key_trends=[],
        ko_summary_steps=[
            "**투자 주체:** 기후에너지환경부, 한국전력공사",
            "**투자 목적:** 직류 산업 수출산업화 지원",
            "**위탁 연구 니즈:** 직류 배전 기술개발과 실증 성과 사업화",
            "**접근 전략:** 표준·인증 체계 마련 및 제도개선",
            "기후에너지환경부와 한국전력공사가 직류 산업 확산을 추진함.",
        ],
        en_summary_steps=[],
        keyword_relevance="전력계통과 직접 연관",
        ko_one_liner="기후에너지환경부와 한국전력공사가 직류 산업 확산을 추진함.",
        rd_match_score=5,
        rd_proposable_area="직류 배전 기술개발",
        rd_fact_basis="K-DC 산업 확산 2026 개최",
    )
    base.update(overrides)
    return SummarizedArticle(**base)


def test_build_daily_html_contains_dashboard_sections() -> None:
    log_date = date(2026, 7, 2)
    articles = [_article()]
    html = build_daily_html(log_date, articles, top_keywords=["전력계통", "스마트그리드"])

    assert "<!DOCTYPE html>" in html
    assert "R&D 기회 스캔 보드" in html
    assert "credChart" in html
    assert "itemsGrid" in html
    assert "직류 산업 확산 추진" in html
    assert "daily_2026-07-02.md" in html


def test_save_daily_report_writes_html(tmp_path: Path) -> None:
    log_date = date(2026, 7, 2)
    path = save_daily_report(
        log_date,
        [_article()],
        output_dir=tmp_path,
        top_keywords=["전력계통"],
    )
    assert path is not None
    assert path.suffix == ".md"
    html_path = tmp_path / "daily_2026-07-02.html"
    assert html_path.exists()
    assert "daily_2026-07-02.html" in path.read_text(encoding="utf-8")
