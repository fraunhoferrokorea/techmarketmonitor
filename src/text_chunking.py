from __future__ import annotations

import os
import re

_CHUNK_CHARS = int(os.getenv("PLAN_CHUNK_CHARS", "9000"))

_PLAN_SECTION_HINTS = (
    "추진전략",
    "중점 추진과제",
    "비전",
    "재정투자",
    "실행과제",
    "국제표준",
    "MOU",
    "공동연구",
    "기술협력",
    "R&D",
    "AI",
    "에너지",
    "ESS",
    "스마트",
    "전력",
    "VPP",
    "표준",
    "프라운호퍼",
)


def normalize_document_text(text: str) -> str:
    text = text.replace("\u0000", " ")
    text = re.sub(r"[·\u00b7]{2,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Alias for plan PDF pipeline.
normalize_plan_text = normalize_document_text


def chunk_text(text: str, chunk_size: int = _CHUNK_CHARS) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            split_at = text.rfind(" ", start + chunk_size // 2, end)
            if split_at > start:
                end = split_at
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


chunk_plan_text = chunk_text


def _chunk_score(chunk: str, keywords: list[str]) -> int:
    lower = chunk.lower()
    score = 0
    for keyword in keywords:
        if keyword.lower() in lower:
            score += 4
    for hint in _PLAN_SECTION_HINTS:
        if hint.lower() in lower:
            score += 1
    return score


def select_relevant_chunks(
    chunks: list[str],
    keywords: list[str],
    max_chunks: int = 5,
) -> list[str]:
    if len(chunks) <= max_chunks:
        return chunks

    scored = sorted(
        enumerate(chunks),
        key=lambda item: _chunk_score(item[1], keywords),
        reverse=True,
    )
    chosen_indices = {0}
    strategy_hints = ("추진전략", "중점 추진과제", "재정투자", "MOU", "공동연구")
    for index, _chunk in scored:
        if len(chosen_indices) >= max_chunks:
            break
        if _chunk_score(chunks[index], keywords) > 0 or any(
            hint in chunks[index] for hint in strategy_hints
        ):
            chosen_indices.add(index)

    while len(chosen_indices) < min(max_chunks, len(chunks)):
        for index, _chunk in scored:
            chosen_indices.add(index)
            if len(chosen_indices) >= max_chunks:
                break

    return [chunks[i] for i in sorted(chosen_indices)]
