from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

from src.attachment_extractor import extract_pdf_from_path
from src.config import PROJECT_ROOT, Settings
from src.models import SummarizedArticle
from src.policy_priority import gov_target_pass_label
from src.llm_utils import extract_json, is_tpd_rate_limit, sleep_for_tpd_limit
from src.summarizer import polish_korean

logger = logging.getLogger(__name__)

_PLAN_OUTPUT_DIR = PROJECT_ROOT / "output" / "plans"
_MAX_MAP_CHUNKS = int(os.getenv("PLAN_MAX_MAP_CHUNKS", "5"))
_REQUEST_DELAY = float(os.getenv("SUMMARIZER_REQUEST_DELAY", "1.0"))
_MAX_RETRIES = 5

from src.text_chunking import (
    _CHUNK_CHARS,
    chunk_plan_text,
    normalize_plan_text,
    select_relevant_chunks,
)

_MAP_SYSTEM = """당신은 한국 정부 마스터플랜·기본계획 문서 분석가입니다.
주어진 문서 일부에서 분석 기준 키워드 및 표준·R&D·에너지·산업 정책과 연관된 사실만 추출합니다.
원문에 없는 내용을 추가하지 마세요. 수치·연도·기관명·과제명은 원문 그대로 유지합니다.
JSON만 반환:
{
  "facts": ["사실 1", "사실 2"],
  "section_hint": "이 구간의 주제 한 줄"
}"""

_REDUCE_SYSTEM = """당신은 프라운호퍼 한국 사무소용 기술 시장 모니터링 분석가입니다.
정부 마스터플랜에서 추출된 사실 목록을 바탕으로, 분석 기준 키워드 관점의 한국어 요약을 작성합니다.
전체 원문을 다루지 말고, 추출된 사실과 계획의 핵심(비전·전략·실행과제·일정·수치)만 반영합니다.
모든 한국어 문장은 명사형 종결(-함/-임/-었음)로 통일합니다.
JSON 스키마:
{
  "summary": "1문장 한국어 헤드라인. 반드시 '출처: <url>'로 끝남",
  "key_trends": ["시장 동향 키워드 1", "시장 동향 키워드 2"],
  "ko_summary_steps": [
    "**개요:** ...",
    "**핵심 내용:** ...",
    "**기술적 차별성:** ...",
    "**시장 파급력:** ...",
    "**투자·미래 전망:** ..."
  ],
  "ko_one_liner": "Executive Summary용 1문장(70~150자, 명사형 종결)",
  "keyword_relevance": "분석 기준 키워드와 이 계획의 연관성 2~4문단(통합 서술, 키워드별 문단 분리 금지)"
}"""


def _file_url(pdf_path: Path) -> str:
    resolved = pdf_path.resolve()
    return resolved.as_uri()


def _default_title(pdf_path: Path) -> str:
    return pdf_path.stem.replace("_", " ").strip()


class PlanDocumentSummarizer:
    def __init__(self, settings: Settings) -> None:
        load_dotenv(PROJECT_ROOT / ".env")
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required for plan summarization")
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self._keywords = settings.analysis_keywords
        self._model = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL", "gemini-2.0-flash-lite")

    def _chat_json(self, system: str, user: str) -> dict:
        response = None
        while response is None:
            for attempt in range(1, _MAX_RETRIES + 1):
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
                    if attempt == _MAX_RETRIES:
                        raise
                    time.sleep(2 ** attempt)
            else:
                break
        return extract_json(response.choices[0].message.content or "{}")

    def extract_facts_from_chunks(
        self,
        chunks: list[str],
        title: str,
        keywords: list[str],
    ) -> list[str]:
        facts: list[str] = []
        kw_label = ", ".join(keywords)
        for index, chunk in enumerate(chunks, start=1):
            logger.info("Plan map %d/%d (%d chars)", index, len(chunks), len(chunk))
            payload = self._chat_json(
                _MAP_SYSTEM,
                (
                    f"문서 제목: {title}\n"
                    f"분석 기준 키워드: {kw_label}\n"
                    f"문서 구간 {index}/{len(chunks)}:\n{chunk[: _CHUNK_CHARS]}"
                ),
            )
            for fact in payload.get("facts") or []:
                cleaned = str(fact).strip()
                if cleaned and cleaned not in facts:
                    facts.append(cleaned)
            if index < len(chunks):
                time.sleep(_REQUEST_DELAY)
        return facts

    def synthesize_plan_summary(
        self,
        title: str,
        source_url: str,
        facts: list[str],
        keywords: list[str],
        source_name: str = "정부 계획서 (로컬 PDF)",
    ) -> SummarizedArticle:
        kw_label = ", ".join(keywords)
        facts_text = "\n".join(f"- {fact}" for fact in facts[:40])
        payload = self._chat_json(
            _REDUCE_SYSTEM,
            (
                f"문서 제목: {title}\n"
                f"출처 URL: {source_url}\n"
                f"분석 기준 키워드: {kw_label}\n"
                f"추출된 관련 사실:\n{facts_text}"
            ),
        )

        summary = polish_korean(str(payload.get("summary", "")).strip())
        if source_url not in summary:
            summary = f"{summary} 출처: {source_url}".strip()

        ko_steps = [
            polish_korean(str(step).strip())
            for step in (payload.get("ko_summary_steps") or [])
            if str(step).strip()
        ]
        keyword_relevance = polish_korean(str(payload.get("keyword_relevance", "")).strip())
        ko_one_liner = polish_korean(str(payload.get("ko_one_liner", "")).strip())
        trends = [str(t).strip() for t in (payload.get("key_trends") or []) if str(t).strip()]

        matched = list(dict.fromkeys([gov_target_pass_label(), *keywords]))

        return SummarizedArticle(
            title=title,
            url=source_url,
            source_name=source_name,
            category="korean",
            published_at=None,
            matched_keywords=matched,
            llm_summary=summary,
            key_trends=trends,
            ko_summary_steps=ko_steps,
            en_summary_steps=[],
            keyword_relevance=keyword_relevance,
            ko_one_liner=ko_one_liner,
        )


def save_plan_text(pdf_path: Path, text: str) -> Path:
    _PLAN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _PLAN_OUTPUT_DIR / f"{pdf_path.stem}.txt"
    out_path.write_text(text, encoding="utf-8")
    return out_path


def save_plan_summary_markdown(pdf_path: Path, article: SummarizedArticle) -> Path:
    """Write plan summary to output/plans/ (not the daily 24h research log)."""
    _PLAN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _PLAN_OUTPUT_DIR / f"{pdf_path.stem}_summary.md"
    lines = [
        f"# {article.title} — 계획서 요약",
        "",
        "> 수동 ingest (`summarize-plan`). 데일리 RSS·24h 수집 범위와 별도 보관.",
        "",
        f"- **출처:** {article.url}",
        f"- **요약 생성일:** {date.today().isoformat()}",
        "",
        "## Executive Summary",
        "",
        article.ko_one_liner or article.llm_summary,
        "",
        "## 요약",
        "",
    ]
    for step in article.ko_summary_steps:
        lines.append(f"- {step}")
    if article.keyword_relevance:
        lines += ["", "## 키워드·프라운호퍼 관련성", "", article.keyword_relevance]
    if article.key_trends:
        lines += ["", "## 동향 키워드", "", ", ".join(article.key_trends)]
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def summarize_plan_pdf(
    pdf_path: Path,
    settings: Settings,
    *,
    title: str | None = None,
    focus_keywords: list[str] | None = None,
    save_text: bool = False,
) -> SummarizedArticle:
    """Summarize a long government plan PDF focused on tracking keywords."""
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)

    doc_title = title or _default_title(pdf_path)
    keywords = focus_keywords or settings.analysis_keywords
    if not keywords:
        raise ValueError("No focus keywords — check keywords.txt")

    raw_text = normalize_plan_text(extract_pdf_from_path(pdf_path))
    if not raw_text:
        raise ValueError(f"Could not extract text from PDF: {pdf_path}")

    if save_text:
        saved = save_plan_text(pdf_path, raw_text)
        logger.info("Saved extracted plan text → %s", saved)

    chunks = chunk_plan_text(raw_text)
    selected = select_relevant_chunks(chunks, keywords)
    logger.info(
        "Plan PDF: %d chars, %d chunks → %d selected for map phase",
        len(raw_text),
        len(chunks),
        len(selected),
    )

    summarizer = PlanDocumentSummarizer(settings)
    facts = summarizer.extract_facts_from_chunks(selected, doc_title, keywords)
    if not facts:
        raise ValueError("No relevant facts extracted — try different keywords or check PDF text quality")

    time.sleep(_REQUEST_DELAY)
    return summarizer.synthesize_plan_summary(
        doc_title,
        _file_url(pdf_path),
        facts,
        keywords,
    )
