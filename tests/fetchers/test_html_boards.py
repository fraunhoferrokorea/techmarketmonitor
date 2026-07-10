from datetime import date

from src.fetchers.html_boards import (
    _parse_kasa,
    _parse_mnd,
    _parse_molit,
    _parse_tipa,
)


def test_parse_molit_rows() -> None:
    html = """
    <tr>
      <td class="bd_title">
        <a href="dtl.jsp?lcmspage=1&amp;id=95092208" class="new">전력망 고도화 추진</a>
      </td>
      <td class="bd_date">2026-07-10</td>
    </tr>
    """
    rows = _parse_molit(html, set())
    assert len(rows) == 1
    title, url, day = rows[0]
    assert title == "전력망 고도화 추진"
    assert "id=95092208" in url
    assert day == date(2026, 7, 10)


def test_parse_mnd_rows() -> None:
    html = """
    <a href="/bbs/mnd/13000005/DPIM_117310/artclView.do" onclick="jf_viewArtcl('mnd', '13000005', 'DPIM_117310')">
      <strong><span>국방부, 한-아세안 방산협력 컨퍼런스 성공적 개최</span></strong>
    </a>
    <td class="td-date">2026.07.09</td>
    """
    rows = _parse_mnd(html, set())
    assert len(rows) == 1
    assert "artclView.do" in rows[0][1]
    assert rows[0][2] == date(2026, 7, 9)


def test_parse_kasa_rows() -> None:
    html = """
    <button onclick="fn_view('444'); return false;" class="board__link">
      <strong class="board__subject-text">미래항공기 플랫폼 확보</strong>
    </button>
    <td class="board__table--date">
        2026-07-10
    </td>
    """
    rows = _parse_kasa(html, set())
    assert len(rows) == 1
    assert "plcyBrfNo=444" in rows[0][1]
    assert rows[0][2] == date(2026, 7, 10)


def test_parse_tipa_rows() -> None:
    html = """
    <td class="subject">
      <a href='/s040102/view/id/17542' title="스마트공장 지원">
        스마트공장 지원
      </a>
    </td>
    <td>소통홍보팀</td>
    <td>81</td>
    <td>2026.07.08</td>
    """
    rows = _parse_tipa(html, set())
    assert len(rows) == 1
    assert rows[0][1].endswith("/s040102/view/id/17542")
    assert rows[0][2] == date(2026, 7, 8)
