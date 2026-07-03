import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fetchers.korea_kr_archive import _parse_expdoc_page


def test_parse_expdoc_page_extracts_rows() -> None:
    html = """
    <tbody>
      <tr>
        <td class="subject"><a href="/archive/expDocView.do?docId=41741">AI 기반 산불확산예측 알고리즘 설명서</a></td>
        <td>산림청</td>
        <td>2026.06.15</td>
        <td></td>
      </tr>
    </tbody>
    """
    seen: set[str] = set()
    articles = _parse_expdoc_page(html, date(2026, 6, 15), seen)
    assert len(articles) == 1
    assert articles[0].title.startswith("AI 기반")
    assert "expDocView.do?docId=41741" in articles[0].url
    assert articles[0].source_name == "정책브리핑 전문자료 산림청"


if __name__ == "__main__":
    test_parse_expdoc_page_extracts_rows()
    print("ok")
