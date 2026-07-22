from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.models import FilteredArticle, SummarizedArticle
from src.rd_targeting import parse_rd_fields

logger = logging.getLogger(__name__)

_GROUNDING_SKIP_VALUES = frozenset(
    {
        "",
        "해당 없음",
        "명시 없음",
        "팩트 부족으로 판단 보류",
        "N/A",
    }
)

_GROUNDING_STOP_TERMS = frozenset(
    {
        "관련",
        "등",
        "및",
        "통해",
        "위해",
        "대한",
        "에서",
        "으로",
        "하는",
        "있는",
        "것으로",
        "것이",
        "기술",
        "개발",
        "연구",
        "분석",
        "투자",
        "제안",
        "가능",
        "필요",
        "향상",
        "도모",
        "연계",
        "확대",
        "기업",
        "정부",
        "국내",
        "해외",
        "시장",
        "산업",
        "전력",
        "에너지",
        "전략",
        "목적",
        "주체",
        "니즈",
        "접근",
        "위탁",
        "고난도",
        "고도화",
        "내재화",
        "국산화",
        "실증",
        "협력",
        "정책",
        "정합",
        "로드맵",
        "사업",
        "과제",
        "프로그램",
        "계획",
        "추진",
        "수립",
        "발표",
        "공모",
        "지원",
        "예산",
        "편성",
        "현상",
        "병목",
        "실적",
        "영향",
        "미칠",
        "것으로",
        "보임",
        "보여",
        "연결",
        "신호",
    }
)

_MONITORING_KEYWORDS = (
    "스마트그리드",
    "파워그리드",
    "전력계통",
    "전력망",
    "송배전",
    "마이크로그리드",
    "수요반응",
    "가상발전소",
    "계통안정",
    "전력품질",
    "에너지고속도로",
    "차세대 전력변환기",
    "HVDC",
    "MMC",
    "STATCOM",
    "배전망 디지털화",
    "Digital Grid",
    "장주기 ESS",
    "계통연계",
    "전력망 사이버보안",
    "그리드포밍",
    "Grid-forming",
    "DC Grid",
    "송전설비",
    "출력예측",
    "smart grid",
    "power grid",
    "microgrid",
)

_SPECULATIVE_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"스마트\s*그리드"), "스마트그리드"),
    (re.compile(r"파워\s*그리드"), "파워그리드"),
    (re.compile(r"전력\s*계통"), "전력계통"),
    (re.compile(r"연계\s*연구"), "연계 연구"),
    (re.compile(r"기술\s*개발\s*및"), "기술 개발 및"),
    (re.compile(r"(?:R\s*&\s*D|연구)\s*(?:를|을)?\s*제안"), "연구 제안"),
    (re.compile(r"제안(?:함|할| 가능|할\s*수\s*있)"), "제안"),
    (re.compile(r"위탁\s*연구"), "위탁 연구"),
    (re.compile(r"실증\s*과제"), "실증 과제"),
    (re.compile(r"전력\s*계통\s*안정(?:성)?\s*향상"), "전력계통 안정성 향상"),
)

_ANALYST_REPORT = re.compile(
    r"증권|투자증권|리서치|목표\s*주가|목표가|"
    r"영업이익|매출\s*전망|실적\s*전망|컨센서스|"
    r"투자\s*의견|매수|중립|비중\s*확대|할인율|"
    r"리포트|주가|주식",
    re.I,
)

_RD_COMMISSION_SIGNAL = re.compile(
    r"연구\s*개발|R\s*&\s*D|위탁|공모|과제|실증|MOU|양해각서|"
    r"예산|투자\s*계획|사업\s*추진|로드\s*맵|로드맵|기술\s*개발|"
    r"국가\s*연구|연구\s*개발\s*(?:지원|사업|과제|공모|투자|예산)",
    re.I,
)

_TERM_RE = re.compile(
    r"[A-Za-z]{2,}(?:\s*&\s*[A-Za-z]+)?|\d+(?:\.\d+)?(?:조|억|만|천|%|포인트)?|[가-힣]{2,}"
)

_RD_STEP_LABELS = {
    "investment_purpose": "투자 목적",
    "pain_point": "위탁 연구 니즈",
    "approach_strategy": "접근 전략",
    "investment_actor": "투자 주체",
    "overview": "개요",
}

_MIN_TERM_LEN = 2
_MIN_GROUNDING_RATIO = 0.45


@dataclass(frozen=True)
class GroundingIssue:
    field: str
    reason: str
    detail: str = ""


def build_source_corpus(article: FilteredArticle | SummarizedArticle) -> str:
    parts = [article.title, article.source_name]
    summary = getattr(article, "summary", None)
    if summary:
        parts.append(summary)
    return normalize_grounding_text(" ".join(parts))


def normalize_grounding_text(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = re.sub(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+", "", cleaned)
    cleaned = cleaned.lower()
    cleaned = cleaned.replace("에너지저장장치", "ess")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_grounding_terms(text: str) -> list[str]:
    normalized = normalize_grounding_text(text)
    terms: list[str] = []
    seen: set[str] = set()
    for match in _TERM_RE.finditer(normalized):
        term = match.group(0).strip()
        if len(term) < _MIN_TERM_LEN or term in _GROUNDING_STOP_TERMS:
            continue
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


def _term_in_source(term: str, source: str) -> bool:
    if term in source:
        return True
    compact = term.replace(" ", "")
    if compact and compact in source.replace(" ", ""):
        return True
    if len(term) >= 4 and term[: max(3, len(term) // 2)] in source:
        return True
    return False


def grounding_ratio(claim: str, source: str) -> float:
    terms = extract_grounding_terms(claim)
    if not terms:
        return 1.0
    matched = sum(1 for term in terms if _term_in_source(term, source))
    return matched / len(terms)


def find_ungrounded_phrases(claim: str, source: str) -> list[str]:
    issues: list[str] = []
    for pattern, label in _SPECULATIVE_PHRASES:
        if pattern.search(claim) and not pattern.search(source):
            issues.append(label)
    for keyword in _MONITORING_KEYWORDS:
        if keyword.lower() in normalize_grounding_text(claim) and keyword.lower() not in source:
            issues.append(keyword)
    return issues


def is_analyst_commentary(source: str) -> bool:
    return bool(_ANALYST_REPORT.search(source)) and not bool(_RD_COMMISSION_SIGNAL.search(source))


def has_source_anchor(claim: str, source: str) -> bool:
    for term in extract_grounding_terms(claim):
        if len(term) >= 3 and _term_in_source(term, source):
            return True
    return False


def should_reset_field(field: str, source: str, *, strict: bool = False) -> bool:
    text = (field or "").strip()
    if text in _GROUNDING_SKIP_VALUES:
        return False
    if find_ungrounded_phrases(text, source):
        return True
    if not strict:
        return False
    if not has_source_anchor(text, source):
        return True
    return grounding_ratio(text, source) < 0.25


def is_field_grounded(field: str, source: str, *, strict: bool = False) -> bool:
    return not should_reset_field(field, source, strict=strict)


def audit_summarized_fields(
    source: FilteredArticle | SummarizedArticle,
    summarized: SummarizedArticle,
) -> list[GroundingIssue]:
    corpus = build_source_corpus(source)
    issues: list[GroundingIssue] = []

    if is_analyst_commentary(corpus):
        issues.append(
            GroundingIssue(
                field="article",
                reason="analyst_report",
                detail="증권사 리포트·목표가 분석 — R&D 발주 신호 아님",
            )
        )

    checks: tuple[tuple[str, str, bool], ...] = (
        ("rd_proposable_area", summarized.rd_proposable_area, True),
        ("rd_fact_basis", summarized.rd_fact_basis, False),
        ("ko_one_liner", summarized.ko_one_liner, True),
        ("keyword_relevance", summarized.keyword_relevance, False),
        ("llm_summary", summarized.llm_summary, False),
    )
    for field_name, value, strict in checks:
        text = (value or "").strip()
        if text in _GROUNDING_SKIP_VALUES:
            continue
        for phrase in find_ungrounded_phrases(text, corpus):
            issues.append(
                GroundingIssue(
                    field=field_name,
                    reason="ungrounded_phrase",
                    detail=phrase,
                )
            )
        if not is_field_grounded(text, corpus, strict=strict):
            issues.append(
                GroundingIssue(
                    field=field_name,
                    reason="low_term_overlap",
                    detail=f"ratio={grounding_ratio(text, corpus):.2f}",
                )
            )

    fields = parse_rd_fields(summarized.ko_summary_steps)
    for key, label in _RD_STEP_LABELS.items():
        if key == "overview":
            continue
        text = fields.get(key, "")
        if text in _GROUNDING_SKIP_VALUES:
            continue
        for phrase in find_ungrounded_phrases(text, corpus):
            issues.append(
                GroundingIssue(field=f"ko_step:{label}", reason="ungrounded_phrase", detail=phrase)
            )
        if not is_field_grounded(text, corpus, strict=True):
            issues.append(
                GroundingIssue(
                    field=f"ko_step:{label}",
                    reason="low_term_overlap",
                    detail=f"ratio={grounding_ratio(text, corpus):.2f}",
                )
            )

    return issues


def _strip_ungrounded_clauses(text: str, source: str) -> str:
    if not text.strip():
        return text
    parts = re.split(r"(?<=[.。!?])\s+|,\s+| 및 ", text.strip())
    kept: list[str] = []
    for part in parts:
        chunk = part.strip(" ,")
        if not chunk:
            continue
        if is_field_grounded(chunk, source, strict=False) and not find_ungrounded_phrases(
            chunk, source
        ):
            kept.append(chunk)
    if kept:
        return " ".join(kept)
    return ""


def _replace_ko_step(steps: list[str], label: str, new_body: str) -> list[str]:
    prefix = f"**{label}:**"
    updated: list[str] = []
    replaced = False
    for step in steps:
        if step.strip().startswith(prefix):
            updated.append(f"{prefix} {new_body}".strip())
            replaced = True
        else:
            updated.append(step)
    if not replaced:
        updated.append(f"{prefix} {new_body}".strip())
    return updated


def _overview_from_steps(steps: list[str]) -> str:
    for step in steps:
        if step.strip().startswith("**개요:**"):
            return re.sub(r"^\*\*개요:\*\*\s*", "", step.strip()).strip()
    return ""


def sanitize_summarized_article(
    source: FilteredArticle,
    summarized: SummarizedArticle,
    *,
    monitoring_keywords: list[str] | None = None,
) -> SummarizedArticle:
    """Drop or reset LLM fields that are not supported by the source article text."""
    from src.press_evidence import collect_press_evidence, format_evidence_basis

    corpus = build_source_corpus(source)
    issues = audit_summarized_fields(source, summarized)
    if issues:
        logger.warning(
            "Fact grounding: sanitized %d issue(s) for %s",
            len(issues),
            summarized.title[:60],
        )
        for issue in issues[:8]:
            logger.info(
                "  - %s (%s): %s",
                issue.field,
                issue.reason,
                issue.detail,
            )

    ko_steps = list(summarized.ko_summary_steps)
    rd_proposable = summarized.rd_proposable_area
    rd_fact_basis = summarized.rd_fact_basis
    ko_one_liner = summarized.ko_one_liner
    keyword_relevance = summarized.keyword_relevance
    rd_match_score = summarized.rd_match_score
    rd_evidence_quotes = list(summarized.rd_evidence_quotes or [])

    analyst = is_analyst_commentary(corpus)

    if analyst:
        rd_proposable = "해당 없음"
        ko_steps = _replace_ko_step(ko_steps, "투자 목적", "해당 없음")
        ko_steps = _replace_ko_step(ko_steps, "위탁 연구 니즈", "팩트 부족으로 판단 보류")
        ko_steps = _replace_ko_step(ko_steps, "접근 전략", "해당 없음")
        rd_match_score = min(rd_match_score or 2, 2)

    if should_reset_field(rd_proposable, corpus, strict=True):
        rd_proposable = "해당 없음"

    if rd_fact_basis and should_reset_field(rd_fact_basis, corpus, strict=False):
        rd_fact_basis = "명시 없음"

    fields = parse_rd_fields(ko_steps)
    for key, label in (
        ("investment_purpose", "투자 목적"),
        ("pain_point", "위탁 연구 니즈"),
        ("approach_strategy", "접근 전략"),
    ):
        value = fields.get(key, "")
        if value in _GROUNDING_SKIP_VALUES:
            continue
        if should_reset_field(value, corpus, strict=True):
            default = (
                "팩트 부족으로 판단 보류"
                if key == "pain_point"
                else "해당 없음"
            )
            ko_steps = _replace_ko_step(ko_steps, label, default)

    if analyst:
        overview = _overview_from_steps(ko_steps)
        if overview and not should_reset_field(overview, corpus, strict=False):
            ko_one_liner = overview
    elif ko_one_liner and should_reset_field(ko_one_liner, corpus, strict=True):
        cleaned = _strip_ungrounded_clauses(ko_one_liner, corpus)
        if (
            cleaned
            and not find_ungrounded_phrases(cleaned, corpus)
            and not should_reset_field(cleaned, corpus, strict=True)
        ):
            ko_one_liner = cleaned
        else:
            overview = _overview_from_steps(ko_steps)
            if overview and not should_reset_field(overview, corpus, strict=False):
                ko_one_liner = overview
            elif cleaned:
                first = re.split(r"\s+및\s+", cleaned, maxsplit=1)[0].strip(" ,")
                if first and not should_reset_field(first, corpus, strict=True):
                    ko_one_liner = first
                else:
                    ko_one_liner = ""
            else:
                ko_one_liner = ""

    if keyword_relevance and should_reset_field(keyword_relevance, corpus, strict=False):
        keyword_relevance = ""

    if rd_proposable == "해당 없음" and analyst:
        fields = parse_rd_fields(ko_steps)
        actor = fields.get("investment_actor", "")
        if actor and not is_field_grounded(actor, corpus, strict=False):
            ko_steps = _replace_ko_step(ko_steps, "투자 주체", "명시 없음")

    # Direct-quote evidence from the (enriched) press corpus.
    kw_pool = list(monitoring_keywords or []) or list(_MONITORING_KEYWORDS)
    kw_pool = list(dict.fromkeys(kw_pool + list(source.matched_keywords or [])))
    evidence = collect_press_evidence(source.summary or "", kw_pool)
    if evidence.quotes:
        rd_evidence_quotes = evidence.quotes
        rd_fact_basis = format_evidence_basis(evidence, fallback=rd_fact_basis)
    elif not rd_evidence_quotes and rd_fact_basis in _GROUNDING_SKIP_VALUES:
        rd_fact_basis = "명시 없음"

    return SummarizedArticle(
        title=summarized.title,
        url=summarized.url,
        source_name=summarized.source_name,
        category=summarized.category,
        published_at=summarized.published_at,
        matched_keywords=summarized.matched_keywords,
        llm_summary=summarized.llm_summary,
        key_trends=summarized.key_trends,
        ko_summary_steps=ko_steps,
        en_summary_steps=summarized.en_summary_steps,
        keyword_relevance=keyword_relevance,
        ko_one_liner=ko_one_liner,
        rd_match_score=rd_match_score,
        rd_proposable_area=rd_proposable,
        rd_fact_basis=rd_fact_basis,
        rd_evidence_quotes=rd_evidence_quotes,
    )
