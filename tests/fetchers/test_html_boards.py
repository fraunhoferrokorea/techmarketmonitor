from datetime import date

from src.fetchers.html_boards import (
    _parse_kaia,
    _parse_kasa,
    _parse_kepco,
    _parse_kiat,
    _parse_krit,
    _parse_mnd,
    _parse_molit,
    _parse_nrf,
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


def test_parse_kaia_rows() -> None:
    html = """
    <tr>
      <td>367</td>
      <td class="t_subject">
        <a href="/portal/bbs/view/B0000058/13123.do?searchCnd=&amp;menuNo=200824&amp;pageIndex=1">국토교통과학기술진흥원-코레일-연구기관 상호협력체결</a>
      </td>
      <td>2026-05-22</td>
    </tr>
    """
    rows = _parse_kaia(html, set())
    assert len(rows) == 1
    assert "B0000058/13123.do" in rows[0][1]
    assert rows[0][2] == date(2026, 5, 22)


def test_parse_krit_rows() -> None:
    html = """
    <a href="#" onclick="fnView('press','','6206','1','','');"><span>110</span>천마 핵심부품국산화 개발 사업 성공적 마무리</a>
    <ul class="writer">
      <li class="date">2026-03-03</li>
      <li class="hits">467</li>
    </ul>
    """
    rows = _parse_krit(html, set())
    assert len(rows) == 1
    assert "nttId=6206" in rows[0][1]
    assert rows[0][2] == date(2026, 3, 3)


def test_parse_nrf_rows() -> None:
    html = """
    <a href="javascript:;" class="table-list-link view_btn"
    data-post_no="277163" data-post_close_yn="N">(연구성과) 소프트 메타표면 개발</a>
    <span class="table-list-date">2026-07-09</span>
    """
    rows = _parse_nrf(html, set())
    assert len(rows) == 1
    assert "postNo=277163" in rows[0][1]
    assert rows[0][2] == date(2026, 7, 9)


def test_parse_kiat_rows() -> None:
    html = """
    <a href="javascript:mainContentsGo('41','98e881b0c3bd43cfa822dfb9f68985f5')">
      <span class="tit_news">KIAT, 글로벌 무대로 나가는 이공계 청년들</span>
      <span class="date">2026-07-03</span>
    </a>
    """
    rows = _parse_kiat(html, set())
    assert len(rows) == 1
    assert "board_id=41" in rows[0][1]
    assert "98e881b0c3bd43cfa822dfb9f68985f5" in rows[0][1]
    assert rows[0][2] == date(2026, 7, 3)


def test_parse_kepco_rows() -> None:
    html = """
    <div class="media-list-item">
      <a href="javascript:fn_Detail('15','3117');">
        <dl>
          <dt><span class="img-wrap"></span></dt>
          <dd>
            <strong class="tit">한전, 청렴·CS 신뢰도약 Week 개최</strong>
            <span class="date">2026-07-22 10:04:05.0</span>
          </dd>
        </dl>
      </a>
    </div>
    """
    rows = _parse_kepco(html, set())
    assert len(rows) == 1
    title, url, day = rows[0]
    assert title == "한전, 청렴·CS 신뢰도약 Week 개최"
    assert "boardMngNo=15" in url
    assert "boardNo=3117" in url
    assert day == date(2026, 7, 22)
