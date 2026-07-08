from datetime import date

from src.fetchers.pacst import _parse_board_page


LIST_HTML = """
<div class="pacst-board-list">
  <ul>
    <li class="pacst-board-list__item">
      <a href="boardView.jsp?post_id=2946&amp;cpage=1&board_id=4">
        <strong>87</strong>
        <div class="pacst-board-list__item-text">
          <p>[보도자료] 국가과학기술자문회의 AI 대전환 국가전략 논의</p>
        </div>
        <span>2026-06-25</span>
      </a>
    </li>
    <li class="pacst-board-list__item">
      <a href="boardView.jsp?post_id=2940&amp;cpage=1&board_id=4">
        <strong>81</strong>
        <div class="pacst-board-list__item-text">
          <p>[보도자료] 이전 보도자료</p>
        </div>
        <span>2026-06-01</span>
      </a>
    </li>
  </ul>
</div>
"""

THUMB_HTML = """
<div class="pacst-board-thumb">
  <ul>
    <li class="pacst-board-thumb__item">
      <a href="advboardView.jsp?post_id=2945&amp;cpage=1&board_id=2">
        <img src="/upload/board/5.JPG" alt="">
        <p>제7회 심의회의 개최(26.6.26)</p>
        <span>2026-06-26</span>
      </a>
    </li>
  </ul>
</div>
"""


def test_parse_list_board_filters_by_date() -> None:
    seen: set[str] = set()
    articles, all_before = _parse_board_page(
        LIST_HTML,
        section="board",
        source_name="PACST 보도자료",
        log_date=date(2026, 6, 25),
        seen_urls=seen,
    )
    assert len(articles) == 1
    assert "AI 대전환" in articles[0].title
    assert articles[0].url.endswith("post_id=2946&board_id=4")
    assert articles[0].source_name == "PACST 보도자료"
    assert all_before is False


def test_parse_thumb_board_extracts_item() -> None:
    seen: set[str] = set()
    articles, all_before = _parse_board_page(
        THUMB_HTML,
        section="adv",
        source_name="PACST 심의회의",
        log_date=date(2026, 6, 26),
        seen_urls=seen,
    )
    assert len(articles) == 1
    assert "심의회의" in articles[0].title
    assert "advboardView.jsp" in articles[0].url
    assert all_before is False
