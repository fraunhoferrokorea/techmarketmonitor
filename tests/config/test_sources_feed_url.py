from __future__ import annotations

from pathlib import Path

from src.config import _load_sources_txt, load_sources
from src.fetchers.registry import build_fetchers


def test_load_sources_txt_no_inline_feed_url(tmp_path: Path) -> None:
    path = tmp_path / "sources.txt"
    path.write_text(
        "산업통상부 보도자료 | https://www.motir.go.kr/kor/article/ATCL3f49a5a8c | korean | post\n"
        "과기정통부 보도자료 | https://www.msit.go.kr/index.do | korean\n",
        encoding="utf-8",
    )
    sources = _load_sources_txt(path)
    assert sources[0]["url"] == "https://www.motir.go.kr/kor/article/ATCL3f49a5a8c"
    assert "feed_url" not in sources[0]
    assert sources[0]["method"] == "POST"


def test_load_sources_merges_feed_url_from_yaml() -> None:
    sources = {s["name"]: s for s in load_sources()}
    msit = sources["과기정통부 보도자료"]
    assert msit["url"] == "https://www.msit.go.kr/index.do"
    assert "rss.do?bbsSeqNo=94" in msit["feed_url"]
    motir = sources["산업통상부 보도자료"]
    assert motir["url"].endswith("/ATCL3f49a5a8c")
    assert motir["feed_url"].endswith("/rss")
    assert motir["method"] == "POST"


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
