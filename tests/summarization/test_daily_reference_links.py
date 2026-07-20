"""Daily report reference links should be clickable on title and summary."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from src.daily_markdown_loader import parse_daily_report
from src.daily_report import (
    _build_executive_summary,
    _build_item_block,
    _build_item_slugs,
    _md_link,
)
from src.models import SummarizedArticle

_URL = "https://www.mcee.go.kr/home/web/board/read.do?menuId=286&boardMasterId=1&boardId=1"


def _sample_article() -> SummarizedArticle:
    return SummarizedArticle(
        title="전력망 고도화 보도자료",
        url=_URL,
        source_name="기후에너지환경부 보도자료",
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


def test_item_block_links_title_and_first_summary() -> None:
    article = _sample_article()
    slug = "1000-전력망-고도화-보도자료"
    block = "\n".join(_build_item_block(article, 1, date(2026, 7, 9), ["전력계통"], slug))
    assert f"### 10:00 [전력망 고도화 보도자료]({_URL})" in block
    assert any(
        line.startswith("  - [") and _URL in line
        for line in block.splitlines()
    )
    assert "- **출처:** 기후에너지환경부 보도자료" in block
    assert f"- **링크/DOI:** {_URL}" in block


def test_loader_unwraps_title_link_and_plain_url(tmp_path: Path) -> None:
    md = tmp_path / "daily_2026-07-09.md"
    md.write_text(
        f"""# 국내 R&D 인텔리전스 데일리 로그

날짜: 2026-07-09

## 항목 기록

<a id="slug"></a>
### 10:00 [전력망 고도화 보도자료]({_URL})

- **자료유형:** 공식발표(IR·정책)
- **출처:** 기후에너지환경부 보도자료
- **저자/발행기관:** 기후에너지환경부 보도자료
- **발행일:** 2026-07-09
- **링크/DOI:** {_URL}
- **요약:**
  - [개요: 전력망 고도화 추진함]({_URL})
- **신뢰도:** A
- **태그:** #규제
""",
        encoding="utf-8",
    )
    entries = parse_daily_report(md, log_date=date(2026, 7, 9))
    assert len(entries) == 1
    assert entries[0]["url"] == _URL
    assert entries[0]["title"] == "전력망 고도화 보도자료"
    assert entries[0]["source_name"] == "기후에너지환경부 보도자료"


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


def test_scan_table_title_links_to_source() -> None:
    article = _sample_article()
    slugs = _build_item_slugs([article])
    text = "\n".join(_build_executive_summary([article], ["전력계통"], slugs))
    assert f"[전력망 고도화 보도자료]({_URL})" in text
    assert f"· [원문]({_URL})" not in text
