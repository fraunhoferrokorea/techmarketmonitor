from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.config import _normalize_keyword, load_settings
from src.fetchers.keyword_search import (
    KeywordSearchFetcher,
    google_news_search_url,
    resolve_google_news_url,
)
from src.fetchers.registry import build_fetchers
from src.filter import match_keywords
from src.korea_scope import is_korea_scoped
from src.models import RawArticle


def test_normalize_keyword_lowercases_mixed_script() -> None:
    assert _normalize_keyword("장주기 ESS") == "장주기 ess"
    assert _normalize_keyword("AI 기반 송전설비 유지관리") == "ai 기반 송전설비 유지관리"
    assert _normalize_keyword("AI 기반 전력계통 운영") == "ai 기반 전력계통 운영"
    assert _normalize_keyword("HVDC") == "hvdc"
    assert _normalize_keyword("전력계통") == "전력계통"


def test_mixed_script_keywords_self_match() -> None:
    settings = load_settings()
    assert match_keywords("장주기 ESS 도입 확대", settings.filter_keywords) == [
        "장주기 ess"
    ]
    assert "ai 기반 송전설비 유지관리" in match_keywords(
        "AI 기반 송전설비 유지관리 시스템 구축",
        settings.filter_keywords,
    )
    assert "ai 기반 전력계통 운영" in match_keywords(
        "AI 기반 전력계통 운영 고도화",
        settings.filter_keywords,
    )
    # Labels keep original casing in matched_keywords for report display.
    assert match_keywords("장주기 ESS 도입", settings.keyword_labels) == ["장주기 ESS"]
    assert "AI 기반 송전설비 유지관리" in match_keywords(
        "AI 기반 송전설비 유지관리",
        settings.keyword_labels,
    )


def test_google_news_search_url_encodes_keyword() -> None:
    url = google_news_search_url("장주기 ESS", days=7)
    assert "news.google.com/rss/search?" in url
    assert "hl=ko" in url
    assert "gl=KR" in url
    assert "when%3A7d" in url or "when:7d" in url


def test_build_fetchers_appends_keyword_search() -> None:
    sources = [
        {
            "name": "산업통상부 보도자료",
            "url": "https://www.motir.go.kr/kor/article/ATCL3f49a5a8c",
            "feed_url": "https://www.motir.go.kr/kor/article/ATCL3f49a5a8c/rss",
            "category": "korean",
            "method": "POST",
        }
    ]
    fetchers = build_fetchers(sources, ["HVDC", "스마트그리드"])
    assert len(fetchers) == 2
    assert fetchers[0].url.endswith("/rss")
    assert isinstance(fetchers[1], KeywordSearchFetcher)
    assert fetchers[1].keywords == ["HVDC", "스마트그리드"]


def test_korea_scope_allows_hangul_dotcom_outlet() -> None:
    article = RawArticle(
        title="한전, 마이크로그리드·스마트그리드 사업 확대",
        url="http://www.e2news.com/news/articleView.html?idxno=332652",
        summary="국내 전력망 고도화",
        source_name="이투뉴스",
        category="korean",
        published_at=datetime.now(tz=timezone.utc),
    )
    assert is_korea_scoped(article)


def test_resolve_google_news_url_parses_garturlres() -> None:
    gnews = (
        "https://news.google.com/rss/articles/"
        "CBMiZ0FVX3lxTE16c2pfZU5Vb04xNTJ2S21NdE1LcWp5LVg5ZU43cG4xOWd5"
        "RWFDR0dWNnpYcEhrYl91eFZrbHljU1NzZy01Q3pNU2NUWk9LNTJGbUNCczFET1Fx"
        "XzJ0WW82NkpGY1plY1E?oc=5"
    )
    page_html = '<div data-n-a-sg="SIG123" data-n-a-ts="1710000000"></div>'
    batch_body = (
        ")]}'\n"
        '[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"http://www.e2news.com/a\\"]",'
        "null,null,[3],\"generic\"]]"
    )

    mock_page = MagicMock()
    mock_page.text = page_html
    mock_page.raise_for_status = MagicMock()

    mock_batch = MagicMock()
    mock_batch.text = batch_body
    mock_batch.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.return_value = mock_page
    mock_client.post.return_value = mock_batch

    with patch("src.fetchers.keyword_search.httpx.Client", return_value=mock_client):
        assert resolve_google_news_url(gnews) == "http://www.e2news.com/a"
