"""Daily report reference links should be clickable markdown."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from src.daily_markdown_loader import parse_daily_report
from src.daily_report import _build_item_block, _build_item_slugs, _md_link
from src.models import SummarizedArticle


def _sample_article() -> SummarizedArticle:
    return SummarizedArticle(
        title="전력망 고도화 보도자료",
        url="https://www.korea.kr/briefing/pressReleaseView.do?newsId=156770276",
        source_name="정책브리핑",
        category="enterprise",
        published_at=datetime(2026, 7, 9, 10, 0),
        matched_keywords=["전력계통"],
        llm_summary="전력망 고도화 추진",
        key_trends=[],
        ko_summary_steps=["개요: 전력망 고도화 추진함", "(해석) 그리드 투자 신호"],
        en_summary_steps=[],
        rd_fact_basis="500MW 해상풍력 계획",
        rd_match_score=3,
        rd_proposable_area="스마트그리드 운영",
    )


def test_md_link_escapes_brackets() -> None:
    assert _md_link("A[B]C", "https://example.com") == "[A［B］C](https://example.com)"


def test_item_block_uses_clickable_source_and_url() -> None:
    article = _sample_article()
    slug = "1000-전력망-고도화-보도자료"
    block = "\n".join(_build_item_block(article, 1, date(2026, 7, 9), ["전력계통"], slug))
    assert (
        "- **출처:** [정책브리핑](https://www.korea.kr/briefing/pressReleaseView.do?newsId=156770276)"
        in block
    )
    assert (
        "- **링크/DOI:** [원문](https://www.korea.kr/briefing/pressReleaseView.do?newsId=156770276)"
        in block
    )


def test_loader_unwraps_markdown_links(tmp_path: Path) -> None:
    md = tmp_path / "daily_2026-07-09.md"
    md.write_text(
        """# 국내 R&D 인텔리전스 데일리 로그

날짜: 2026-07-09

## 항목 기록

<a id="slug"></a>
### 10:00 전력망 고도화 보도자료

- **자료유형:** 공식발표(IR·정책)
- **출처:** [정책브리핑](https://www.korea.kr/briefing/pressReleaseView.do?newsId=156770276)
- **저자/발행기관:** 정책브리핑
- **발행일:** 2026-07-09
- **링크/DOI:** [원문](https://www.korea.kr/briefing/pressReleaseView.do?newsId=156770276)
- **요약:**
  - 개요: 전력망 고도화 추진함
- **신뢰도:** A
- **태그:** #규제
""",
        encoding="utf-8",
    )
    entries = parse_daily_report(md, log_date=date(2026, 7, 9))
    assert len(entries) == 1
    assert entries[0]["url"] == (
        "https://www.korea.kr/briefing/pressReleaseView.do?newsId=156770276"
    )
    assert entries[0]["source_name"] == "정책브리핑"


def test_loader_keeps_plain_url_compat(tmp_path: Path) -> None:
    md = tmp_path / "daily_2026-07-08.md"
    md.write_text(
        """# 로그

## 항목 기록

### 09:00 구형식

- **자료유형:** 기사
- **출처:** 연합뉴스
- **발행일:** 2026-07-08
- **링크/DOI:** https://www.yna.co.kr/view/AKR20260708030000008
- **요약:**
  - 개요: 테스트임
- **신뢰도:** A
- **태그:** #기술
""",
        encoding="utf-8",
    )
    entries = parse_daily_report(md, log_date=date(2026, 7, 8))
    assert entries[0]["url"] == "https://www.yna.co.kr/view/AKR20260708030000008"
    assert entries[0]["source_name"] == "연합뉴스"


def test_scan_table_includes_external_원문_link() -> None:
    from src.daily_report import _build_executive_summary

    article = _sample_article()
    slugs = _build_item_slugs([article])
    text = "\n".join(_build_executive_summary([article], ["전력계통"], slugs))
    assert "· [원문](https://www.korea.kr/briefing/pressReleaseView.do?newsId=156770276)" in text
