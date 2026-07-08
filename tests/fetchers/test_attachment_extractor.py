from datetime import datetime, timezone
from unittest.mock import patch

from src.attachment_extractor import discover_pdf_urls, extract_hwpx_text, extract_pdf_text
from src.article_enrichment import enrich_raw_article
from src.models import RawArticle


def test_discover_korea_kr_pdf_links() -> None:
    html = """
    <a href="/common/download.do?fileId=198497842&amp;tblKey=GMN">보도자료.pdf</a>
    <a href="/common/download.do?fileId=198497843&amp;tblKey=GMN">붙임.hwp</a>
    """
    urls = discover_pdf_urls(html, "https://www.korea.kr/briefing/pressReleaseView.do?newsId=1")
    assert urls[0] == "https://www.korea.kr/common/download.do?fileId=198497842&tblKey=GMN"


def test_discover_msit_pdf_only() -> None:
    html = """
    fn_download('54251', '1', 'hwpx');
    fn_download('54251', '2', 'pdf');
    """
    urls = discover_pdf_urls(html, "https://www.msit.go.kr/bbs/view.do")
    assert len(urls) == 1
    assert "atchFileNo=54251" in urls[0]
    assert "fileOrd=2" in urls[0]


def test_extract_hwpx_text_from_zip_xml() -> None:
    import io
    import zipfile

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<hp:t>스마트그리드</hp:t><hp:t> 전력계통</hp:t>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Contents/section0.xml", xml)
    text = extract_hwpx_text(buffer.getvalue())
    assert "스마트그리드" in text
    assert "전력계통" in text


def test_enrich_includes_pdf_marker(monkeypatch=None) -> None:
    article = RawArticle(
        title="제6차 국가표준기본계획 발표",
        url="https://www.korea.kr/briefing/pressReleaseView.do?newsId=1",
        summary="짧은 RSS 요약",
        source_name="정책브리핑 산업통상부",
        category="korean",
        published_at=datetime.now(tz=timezone.utc),
    )
    fake_html = '<a href="/common/download.do?fileId=1&tblKey=GMN">a.pdf</a>'

    with patch("src.article_enrichment._fetch_page_html", return_value=fake_html):
        with patch("src.article_enrichment.fetch_plan_attachment_texts", return_value=["PDF 본문 텍스트"]):
            enriched = enrich_raw_article(article)

    assert "[첨부 문서 원문 1]" in enriched.summary
    assert "PDF 본문 텍스트" in enriched.summary
