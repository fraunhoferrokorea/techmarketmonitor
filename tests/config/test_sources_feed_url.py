from __future__ import annotations

from pathlib import Path

from src.config import _load_sources_md, load_sources
from src.fetchers.registry import build_fetchers


def test_load_sources_md_named_and_simple_links(tmp_path: Path) -> None:
    path = tmp_path / "sources.md"
    path.write_text(
        "# sources\n"
        "- **산업통상부 보도자료** — [https://www.motir.go.kr/kor/article/ATCL3f49a5a8c]"
        "(https://www.motir.go.kr/kor/article/ATCL3f49a5a8c)\n"
        "- [과기정통부 보도자료](https://www.msit.go.kr/index.do)\n"
        "- 추가 소스 [새 매체](https://example.com/news)\n",
        encoding="utf-8",
    )
    sources = _load_sources_md(path)
    assert [s["name"] for s in sources] == [
        "산업통상부 보도자료",
        "과기정통부 보도자료",
        "새 매체",
    ]
    assert sources[0]["url"].endswith("/ATCL3f49a5a8c")
    assert sources[2]["url"] == "https://example.com/news"
    assert all("feed_url" not in s for s in sources)


def test_load_sources_merges_feed_url_and_method_from_yaml() -> None:
    sources = {s["name"]: s for s in load_sources()}
    msit = sources["과기정통부 보도자료"]
    assert msit["url"] == "https://www.msit.go.kr/index.do"
    assert "rss.do?bbsSeqNo=94" in msit["feed_url"]
    motir = sources["산업통상부 보도자료"]
    assert motir["url"].endswith("/ATCL3f49a5a8c")
    assert motir["feed_url"].endswith("/rss")
    assert motir["method"] == "POST"
    assert sources["국토교통부 보도자료"]["method"] == "HTML"


def test_build_fetchers_prefers_feed_url() -> None:
    sources = [
        {
            "name": "산업통상부 보도자료",
            "url": "https://www.motir.go.kr/kor/article/ATCL3f49a5a8c",
            "feed_url": "https://www.motir.go.kr/kor/article/ATCL3f49a5a8c/rss",
            "category": "korean",
            "method": "POST",
        }
    ]
    fetchers = build_fetchers(sources, [])
    assert len(fetchers) == 1
    assert fetchers[0].url.endswith("/rss")
    assert fetchers[0].method == "POST"


def test_md_only_link_is_fetched_via_url() -> None:
    sources = [
        {
            "name": "새 매체",
            "url": "https://example.com/rss.xml",
            "category": "korean",
        }
    ]
    fetchers = build_fetchers(sources, [])
    assert len(fetchers) == 1
    assert fetchers[0].url == "https://example.com/rss.xml"
