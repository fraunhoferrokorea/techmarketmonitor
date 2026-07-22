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


def test_load_keyword_groups_from_section_headers(tmp_path: Path) -> None:
    from src.config import load_keyword_groups

    kw_file = tmp_path / "keywords.txt"
    kw_file.write_text(
        "# intro\n"
        "# ── 전력·에너지 (Fraunhofer 핵심) ───────────────────\n"
        "HVDC\n"
        "전력계통\n"
        "# ── 제조·AI ───────────────────────────────────────\n"
        "제조AI\n"
        "스마트공장\n",
        encoding="utf-8",
    )
    groups = load_keyword_groups(kw_file)
    assert [g.label for g in groups] == ["전력·에너지", "제조·AI"]
    assert list(groups[0].keywords) == ["HVDC", "전력계통"]
    assert list(groups[1].keywords) == ["제조AI", "스마트공장"]


def test_load_settings_keyword_groups_match_file() -> None:
    settings = load_settings()
    assert settings.keyword_groups
    assert settings.keyword_groups[0].label == "전력·에너지"
    assert "HVDC" in settings.keyword_groups[0].keywords
    assert sum(len(g.keywords) for g in settings.keyword_groups) == len(
        settings.keyword_labels
    )