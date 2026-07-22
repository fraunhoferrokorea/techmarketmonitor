from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

from src.config import PROJECT_ROOT, Settings
from src.llm_utils import MAX_RETRIES, REQUEST_DELAY, extract_json, is_tpd_rate_limit, sleep_for_tpd_limit
from src.models import FilteredArticle, SummarizedArticle
from src.policy_priority import gov_target_pass_label, is_gov_target, is_plan_document
from src.text_chunking import (
    _CHUNK_CHARS,
    chunk_plan_text,
    normalize_document_text,
    select_relevant_chunks,
)

logger = logging.getLogger(__name__)

_LONG_CONTENT_THRESHOLD = int(os.getenv("GOV_LONG_CONTENT_CHARS", "10000"))
_PLAN_CONTENT_THRESHOLD = int(os.getenv("GOV_PLAN_CONTENT_CHARS", "3000"))
_MAP_MAX_CHUNKS = int(os.getenv("GOV_MAP_MAX_CHUNKS", "3"))
_PLAN_MAP_MAX_CHUNKS = int(os.getenv("GOV_PLAN_MAP_MAX_CHUNKS", "5"))

_MAP_SYSTEM = """당신은 프라운호퍼 한국 사무소용 R&D·기술협력 타깃팅 분석가입니다.
정부·공공기관 발표 원문 일부에서, 프라운호퍼 협력·기술이전·R&D 사업 기회와 연관된 사실만 추출합니다.
우선 추출: 투자·예산·사업기간, 주관/참여 기관, MOU·공동연구·기술이전, 표준·인증·실증, 기술 격차·로드맵, 분석 키워드 연관 내용.
팩트체크:
1) 원문에 없는 내용·수치·기관명 추가 금지. 수치·연도·기관명은 원문 그대로.
2) 가능하면 원문 구절을 「」로 직접 인용해 facts에 넣음(의역보다 인용 우선).
3) 분석 의견·추론은 facts에 넣지 말 것. 의견이 있으면 별도 "opinions"에 '(의견)' 접두로만.
JSON만 반환:
{
  "facts": ["「원문 인용 또는 팩트」", "사실 2"],
  "opinions": ["(의견) …"],
  "section_hint": "이 구간 주제 한 줄"
}"""


def needs_focused_summarization(article: FilteredArticle) -> bool:
    if not is_gov_target(article):
        return False
    if is_plan_document(article):
        return len(article.summary) >= _PLAN_CONTENT_THRESHOLD
    return len(article.summary) >= _LONG_CONTENT_THRESHOLD


class FocusedDocumentSummarizer:
    """Map-reduce summarizer for long government originals (plans, PDFs, enriched pages)."""

    def __init__(self, settings: Settings) -> None:
        load_dotenv(PROJECT_ROOT / ".env")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self.client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL"))
        self._keywords = settings.analysis_keywords
        self._model = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL", "gemini-2.0-flash-lite")

    def _chat_json(self, system: str, user: str) -> dict:
        response = None
        while response is None:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=self._model,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.2,
                    )
                    break
                except RateLimitError as exc:
                    if is_tpd_rate_limit(exc):
                        sleep_for_tpd_limit(exc)
                        break
                    if attempt == MAX_RETRIES:
                        raise
                    time.sleep(2 ** attempt)
            else:
                break
        return extract_json(response.choices[0].message.content or "{}")

    def extract_facts(self, text: str, title: str, max_chunks: int = _MAP_MAX_CHUNKS) -> list[str]:
        normalized = normalize_document_text(text)
        chunks = chunk_plan_text(normalized)
        selected = select_relevant_chunks(chunks, self._keywords, max_chunks=max_chunks)
        facts: list[str] = []
        opinions: list[str] = []
        kw_label = ", ".join(self._keywords)

        for index, chunk in enumerate(selected, start=1):
            logger.info("Focused map %d/%d (%d chars): %s", index, len(selected), len(chunk), title[:50])
            payload = self._chat_json(
                _MAP_SYSTEM,
                (
                    "프라운호퍼 한국 사무소 관점: 협력·기술이전·R&D 사업·표준·실증 기회 위주로 추출.\n"
                    "원문에 없는 내용 금지. 가능하면 「」 직접 인용. 의견은 opinions에만.\n"
                    f"문서/발표 제목: {title}\n"
                    f"분석 기준 키워드: {kw_label}\n"
                    f"원문 구간 {index}/{len(selected)}:\n{chunk[:_CHUNK_CHARS]}"
                ),
            )
            for fact in payload.get("facts") or []:
                cleaned = str(fact).strip()
                if cleaned.startswith("(의견)"):
                    if cleaned not in opinions:
                        opinions.append(cleaned)
                    continue
                if cleaned and cleaned not in facts:
                    facts.append(cleaned)
            for opinion in payload.get("opinions") or []:
                cleaned = str(opinion).strip()
                if not cleaned:
                    continue
                if not cleaned.startswith("(의견)"):
                    cleaned = f"(의견) {cleaned}"
                if cleaned not in opinions:
                    opinions.append(cleaned)
            if index < len(selected):
                time.sleep(REQUEST_DELAY)
        # Keep opinions available for reduce via attribute (facts-only return for callers).
        self._last_opinions = opinions
        return facts

    def summarize_article(self, article: FilteredArticle) -> SummarizedArticle:
        from src.summarizer import SYSTEM_PROMPT

        max_chunks = _PLAN_MAP_MAX_CHUNKS if is_plan_document(article) else _MAP_MAX_CHUNKS
        facts = self.extract_facts(article.summary, article.title, max_chunks=max_chunks)
        if not facts:
            raise ValueError(f"No relevant facts extracted for: {article.title[:60]}")

        facts_text = "\n".join(f"- {fact}" for fact in facts[:40])
        opinions = getattr(self, "_last_opinions", []) or []
        opinions_text = (
            "\n".join(f"- {op}" for op in opinions[:10])
            if opinions
            else "(없음)"
        )
        kw_label = ", ".join(self._keywords)

        time.sleep(REQUEST_DELAY)
        payload = self._chat_json(
            SYSTEM_PROMPT,
            (
                "아래는 정부·공공기관 발표 원문에서 추출한 사실·의견 목록입니다. "
                "전체 원문이 아닌 이 목록만 바탕으로 프라운호퍼 한국 사무소 관점 요약을 작성하세요.\n"
                "규칙: (1) facts에 없는 내용 추가 금지 (2) 「」 직접 인용 유지 "
                "(3) 의견은 keyword_relevance·위탁/접근에만 '(의견)'으로 줄 바꿔 분리.\n\n"
                f"Title: {article.title}\n"
                f"URL: {article.url}\n"
                f"Source: {article.source_name} ({article.category})\n"
                f"Matched keywords: {', '.join(article.matched_keywords)}\n"
                f"Analysis baseline keywords: {kw_label}\n"
                f"Extracted facts from original document:\n{facts_text}\n"
                f"Extracted opinions (optional, not facts):\n{opinions_text}"
            ),
        )
        return _article_from_payload(article, payload)


def _article_from_payload(article: FilteredArticle, payload: dict) -> SummarizedArticle:
    from src.summarizer import _coerce_text, polish_korean, polish_rd_field, polish_rd_ko_steps

    summary = polish_korean(_coerce_text(payload.get("summary")))
    if article.url not in summary:
        summary = f"{summary} 출처: {article.url}".strip()

    ko_steps = polish_rd_ko_steps(
        [str(step).strip() for step in (payload.get("ko_summary_steps") or []) if str(step).strip()]
    )
    keyword_relevance = polish_korean(_coerce_text(payload.get("keyword_relevance")))
    ko_one_liner = polish_korean(_coerce_text(payload.get("ko_one_liner")))
    trends = [str(t).strip() for t in (payload.get("key_trends") or []) if str(t).strip()]
    rd_proposable_area = polish_rd_field(_coerce_text(payload.get("rd_proposable_area")))
    rd_fact_basis = polish_korean(_coerce_text(payload.get("fact_basis")))
    raw_score = payload.get("rd_match_score", 0)
    try:
        rd_match_score = max(1, min(5, int(raw_score)))
    except (TypeError, ValueError):
        rd_match_score = 0

    matched = list(article.matched_keywords)
    label = gov_target_pass_label()
    if label not in matched:
        matched.insert(0, label)

    return SummarizedArticle(
        title=article.title,
        url=article.url,
        source_name=article.source_name,
        category=article.category,
        published_at=article.published_at,
        matched_keywords=matched,
        llm_summary=summary,
        key_trends=trends,
        ko_summary_steps=ko_steps,
        en_summary_steps=[],
        keyword_relevance=keyword_relevance,
        ko_one_liner=ko_one_liner,
        rd_match_score=rd_match_score,
        rd_proposable_area=rd_proposable_area,
        rd_fact_basis=rd_fact_basis,
    )


def summarize_with_focus_if_needed(
    article: FilteredArticle,
    settings: Settings,
    standard_summarize,
) -> SummarizedArticle:
    """Use map-reduce when enriched government originals exceed the length threshold."""
    if needs_focused_summarization(article):
        logger.info(
            "Long gov original (%d chars) — focused map-reduce: %s",
            len(article.summary),
            article.title[:60],
        )
        return FocusedDocumentSummarizer(settings).summarize_article(article)
    return standard_summarize(article)
