from __future__ import annotations

from pathlib import Path

from src.config import _load_keywords_config, load_settings


def test_top3_is_first_three_keyword_lines(tmp_path: Path) -> None:
    kw_file = tmp_path / "keywords.txt"
    kw_file.write_text(
        "# header comment\n"
        "HVDC\n"
        "전력계통\n"
        "스마트그리드\n"
        "BESS\n",
        encoding="utf-8",
    )
    labels, normalized, top3 = _load_keywords_config(kw_file)
    assert top3 == ["HVDC", "전력계통", "스마트그리드"]
    assert labels == ["HVDC", "전력계통", "스마트그리드", "BESS"]
    assert normalized[0] == "hvdc"


def test_load_settings_top3_matches_file_order() -> None:
    settings = load_settings()
    assert settings.analysis_keywords == settings.keyword_labels[:3]
    assert len(settings.analysis_keywords) == 3
    assert settings.analysis_keywords[0] == "전력계통"
