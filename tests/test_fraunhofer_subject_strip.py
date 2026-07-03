import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rd_targeting import format_rd_link_point
from src.summarizer import strip_implicit_fraunhofer_subject


def test_strip_leading_fraunhofer_subject() -> None:
    raw = (
        "Fraunhofer는 전력계통 안정성 및 스마트그리드 기술 개발에 대한 "
        "기술 지원을 제공할 수 있는 파트ner십을 제안할 수 있음"
    )
    cleaned = strip_implicit_fraunhofer_subject(raw)
    assert not cleaned.startswith("Fraunhofer")
    assert cleaned.startswith("전력계통")


def test_strip_fraunhofer_possessive_mid_sentence() -> None:
    raw = (
        "오라클의 AI 인프라 확장에 대한 관심을 끌기 위해, "
        "Fraunhofer의 AI 데이터센터 인프라 관련 기술과 협력할 수 있는 기회를 제안할 수 있음"
    )
    cleaned = strip_implicit_fraunhofer_subject(raw)
    assert "Fraunhofer" not in cleaned
    assert "AI 데이터센터" in cleaned


def test_strip_preserves_fraunhofer_as_modifier_without_particle() -> None:
    raw = "MSIT 디지털·에너지 R&D 정책 목표와 Fraunhofer 계통 실증 역량 정합성 강조"
    assert strip_implicit_fraunhofer_subject(raw) == raw


def test_strip_skips_placeholder_values() -> None:
    assert strip_implicit_fraunhofer_subject("해당 없음") == "해당 없음"
    assert strip_implicit_fraunhofer_subject("팩트 부족으로 판단 보류") == "팩트 부족으로 판단 보류"


def test_format_rd_link_point_prefers_proposable_area() -> None:
    result = format_rd_link_point(
        "Fraunhofer가 스마트그리드 실증 R&D를 제안할 수 있음",
        "팩트 부족으로 판단 보류",
    )
    assert "Fraunhofer" not in result
    assert "스마트그리드" in result


if __name__ == "__main__":
    test_strip_leading_fraunhofer_subject()
    test_strip_fraunhofer_possessive_mid_sentence()
    test_strip_preserves_fraunhofer_as_modifier_without_particle()
    test_strip_skips_placeholder_values()
    test_format_rd_link_point_prefers_proposable_area()
    print("ok")
