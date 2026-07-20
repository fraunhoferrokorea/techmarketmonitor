from __future__ import annotations

from pathlib import Path

from src.config import _load_keywords_config, _normalize_keyword, load_settings


def test_all_keywords_used_for_analysis_and_filter(tmp_path: Path) -> None:
    kw_file = tmp_path / "keywords.txt"
    kw_file.write_text(
        "# header comment\n"
        "HVDC\n"
        "전력계통\n"
        "스마트그리드\n"
        "BESS\n"
        "에너지고속도로\n",
        encoding="utf-8",
    )
    labels, normalized, analysis, filter_kw = _load_keywords_config(kw_file)
    assert labels == ["HVDC", "전력계통", "스마트그리드", "BESS", "에너지고속도로"]
    assert analysis == labels
    assert filter_kw == normalized
    assert normalized[0] == "hvdc"
    assert len(filter_kw) == 5


def test_load_settings_uses_all_keywords_for_filter() -> None:
    settings = load_settings()
    assert settings.filter_keywords == [
        _normalize_keyword(k) for k in settings.keyword_labels
    ]
    assert settings.filter_keywords[0] == "전력계통"
    assert len(settings.filter_keywords) == len(settings.keyword_labels)
    assert len(settings.filter_keywords) > 5


def test_load_settings_analysis_matches_full_file_order() -> None:
    settings = load_settings()
    assert settings.analysis_keywords == settings.keyword_labels
    assert len(settings.analysis_keywords) == len(settings.keyword_labels)
    assert settings.analysis_keywords[0] == "전력계통"
    assert "재생에너지 출력예측" in settings.analysis_keywords
