from pathlib import Path

from src.attachment_extractor import extract_pdf_from_path
from src.text_chunking import chunk_plan_text, normalize_plan_text, select_relevant_chunks


def test_select_relevant_chunks_prefers_keyword_sections() -> None:
    chunks = [
        "I. 수립 배경 법적 근거",
        "유통물류 매출 동향 일반 통계",
        "VI. 중점 추진과제 스마트그리드 ESS VPP 전력계통 표준",
        "부록 표 목록",
    ]
    selected = select_relevant_chunks(chunks, ["전력계통", "스마트그리드", "VPP"], max_chunks=2)
    assert chunks[0] in selected
    assert chunks[2] in selected


def test_extract_user_sample_pdf_if_present() -> None:
    sample = Path(r"c:\Users\Admin\Downloads\제6차 국가표준기본계획(2026-2030).pdf")
    if not sample.is_file():
        return
    text = normalize_plan_text(extract_pdf_from_path(sample))
    assert len(text) > 10000
    chunks = chunk_plan_text(text)
    assert len(chunks) >= 3
    selected = select_relevant_chunks(chunks, ["전력계통", "스마트그리드", "파워그리드"])
    assert len(selected) >= 2
