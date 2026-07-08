from __future__ import annotations

import os
import re

from src.models import FilteredArticle, RawArticle, SummarizedArticle
from src.policy_priority import gov_target_score, is_gov_target
from src.summarizer import polish_rd_field, strip_implicit_fraunhofer_subject

_RELEVANCE_RANK = {"direct": 0, "indirect": 1, "weak": 2, "none": 3}
_CONTEXT_POWER_HINT = re.compile(
    r"전력계통|파워그리드|스마트그리드|전력망|송배전|BESS|에너지저장|"
    r"마이크로그리드|수요반응|가상발전소|VPP|계통안정|전력품질|"
    r"power\s*grid|smart\s*grid|microgrid|grid\s*stability",
    re.I,
)

# Articles with these signals are prioritized over pure technology news.
_INVESTMENT_SIGNAL = re.compile(
    r"투자|예산|협력|로드\s*맵|로드맵|기술\s*확보|"
    r"invest(?:ment|ing)?|budget|funding|road\s*map|collaborat|"
    r"M\s*&\s*A|인수|합병|R\s*&\s*D|연구\s*개발|위탁|사업\s*기간|"
    r"국산화|내재화|고도화|공모|과제|실증|MOU|양해각서",
    re.I,
)

_KOREA_HINT = re.compile(
    r"한국|대한민국|국내|Korea|Korean|서울|"
    r"과기정통부|과학기술정보통신부|산업통상|중소벤처|중기부|"
    r"국토교통|환경부|산림청|방위사업청|기후에너지|보건복지|교육부|"
    r"MOTIE|MSIT|IITP|KISTEP|ETRI|KAIST|삼성|SK|LG|현대|포스코|"
    r"한국전력|KEPCO|LS\s*일렉트릭|HD현대|진흥원|연구원|"
    r"\.go\.kr|korea\.kr",
    re.I,
)

_RD_HEADING_LABELS: tuple[tuple[str, str], ...] = (
    ("투자 주체", "investment_actor"),
    ("투자 목적", "investment_purpose"),
    ("위탁 연구 니즈", "pain_point"),
    ("접근 전략", "approach_strategy"),
)

_FOREIGN_ONLY_MARKERS = (
    "국내 주체: 해당 없음",
    "국내 주체:해당 없음",
    "국내 타겟: 해당 없음",
    "해외만",
    "해외 주체",
)

MONTHLY_RD_MIN_SCORE = int(os.getenv("MONTHLY_RD_MIN_SCORE", "4"))

_KEYWORD_RD_DELTA = {"direct": 1, "indirect": 0, "weak": -1, "none": -2}
_KEYWORD_RD_CAP = {"direct": 5, "indirect": 5, "weak": 4, "none": 3}

# Field trips, extracurricular programs, and career events — not R&D news even if
# "research" or industry keywords appear in the title.
_NON_RD_EDUCATION_EVENT = re.compile(
    r"비교과\s*프로그램"
    r"|협력형\s*비교과"
    r"|현장\s*체험|현장체험"
    r"|현장\s*교육|현장교육"
    r"|현장\s*견학|산업\s*견학|견학\s*프로그램"
    r"|(?:(?:대학|대학교|대학원)(?:생|\s*생)?|학생\s*\d+\s*명).*?(?:산업\s*현장|산업체\s*방문|현장\s*탐방)"
    r"|(?:산업\s*현장|산업체\s*방문).*?(?:대학생|대학원생|학생\s*\d+\s*명)"
    r"|산업체\s*방문\s*형?\s*교육"
    r"|채용\s*연계\s*인턴십|인턴십.*?채용\s*연계"
    r"|진로\s*교육|진로\s*탐색|취업\s*연계\s*교육",
    re.I,
)

_NON_RD_EDUCATION_RD_OVERRIDE = re.compile(
    r"연구\s*개발|R\s*&\s*D"
    r"|(?:연구|개발)\s*(?:과제|성과|결과|수행)"
    r"|특허|(?:동료\s*)?심사\s*논문"
    r"|실증\s*(?:사업|과제|연구|프로젝트|단지|시험)"
    r"|기술\s*개발|신기술\s*개발"
    r"|(?:예산|투자|공모).*?(?:연구|개발|R&D|과제)"
    r"|정책\s*발표|로드\s*맵|로드맵"
    r"|산업\s*현장\s*실증",
    re.I,
)

# Academic / epidemiological findings without a funder or commissioning signal.
_RESEARCH_OUTCOME_ONLY = re.compile(
    r"메타\s*분석|meta\s*-?\s*analysis"
    r"|상관관계|correlation"
    r"|역학\s*연구|epidemiol"
    r"|cohort\s*study|임상\s*(?:시험|연구)\s*결과"
    r"|동료\s*심사|peer\s*-?\s*review|학술\s*논문"
    r"|(?:연구|분석|조사).*?(?:결과|발견|규명|밝혀|확인)"
    r"|(?:연구|개발)\s*(?:결과|성과)\s*(?:발표|공개)"
    r"|(?:결과|성과|발견)\s*(?:발표|공개|발표됨)"
    r"|위험.*?(?:%|퍼센트|배\s*↑|배\s*증가|증가|상승)"
    r"|암\s*위험|질병\s*위험|건강\s*위험"
    r"|(?:대학|연구원|병원).*?(?:연구|분석).*?(?:발표|규명|밝혀)",
    re.I,
)

# Budget / program / commissioning signals — stricter than _INVESTMENT_SIGNAL
# (which also matches bare "연구개발" in outcome-only headlines).
_RD_FUNDING_SIGNAL = re.compile(
    r"투자|예산|편성|협력|로드\s*맵|로드맵|기술\s*확보|"
    r"invest(?:ment|ing)?|budget|funding|road\s*map|collaborat|"
    r"M\s*&\s*A|인수|합병|위탁|사업\s*기간|"
    r"국산화|내재화|고도화|공모|과제|실증|MOU|양해각서|"
    r"지원\s*사업|연구\s*개발\s*(?:지원|사업|과제|공모|투자|예산)|"
    r"R\s*&\s*D\s*(?:지원|사업|과제|공모|투자|budget|funding)|"
    r"(?:예산|투자|공모|지원).*?(?:연구|개발|R&D|과제)|"
    r"정책\s*발표|(?:추진|시행)\s*(?:계획|사업)|"
    r"실증\s*(?:사업|과제|프로젝트|단지)",
    re.I,
)


def format_rd_link_point(*candidates: str) -> str:
    """Pick the best R&D linkage sentence and drop redundant Fraunhofer subject."""
    for raw in candidates:
        text = (raw or "").strip()
        if not text or text in _FOREIGN_ONLY_MARKERS or text in (
            "해당 없음",
            "명시 없음",
            "팩트 부족으로 판단 보류",
        ):
            continue
        cleaned = polish_rd_field(text)
        if cleaned:
            return cleaned
    return "명시 없음"


def _display_rd_field(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    return strip_implicit_fraunhofer_subject(cleaned)


def _exclusion_source_text(
    article: RawArticle | FilteredArticle | SummarizedArticle,
) -> str:
    """Source-facing text only — ignore LLM R&D fields that can false-trigger overrides."""
    parts = [article.title, article.source_name]
    summary = getattr(article, "summary", None)
    if summary:
        parts.append(summary)
    else:
        llm_summary = getattr(article, "llm_summary", None)
        if llm_summary:
            parts.append(llm_summary)
    return " ".join(parts)


def is_non_rd_program_news(
    article: RawArticle | FilteredArticle | SummarizedArticle,
) -> bool:
    """True for student field trips, tours, and career programs without R&D substance."""
    text = _exclusion_source_text(article)
    if not _NON_RD_EDUCATION_EVENT.search(text):
        return False
    if _NON_RD_EDUCATION_RD_OVERRIDE.search(text):
        return False
    return True


def is_research_outcome_without_investment_signal(
    article: RawArticle | FilteredArticle | SummarizedArticle,
) -> bool:
    """True for academic/epidemiological findings with no funder or commissioning signal."""
    if is_gov_target(article):
        return False
    text = _exclusion_source_text(article)
    if not _RESEARCH_OUTCOME_ONLY.search(text):
        return False
    if _RD_FUNDING_SIGNAL.search(text):
        return False
    return True


def is_excluded_rd_news(
    article: RawArticle | FilteredArticle | SummarizedArticle,
) -> bool:
    """True when article should be dropped from R&D news collection and scoring."""
    return is_non_rd_program_news(article) or is_research_outcome_without_investment_signal(
        article
    )


def _combined_text(article: RawArticle | FilteredArticle | SummarizedArticle) -> str:
    parts = [article.title, article.source_name]
    summary = getattr(article, "summary", None)
    if summary:
        parts.append(summary)
    llm_summary = getattr(article, "llm_summary", None)
    if llm_summary:
        parts.append(llm_summary)
    for step in getattr(article, "ko_summary_steps", None) or []:
        parts.append(str(step))
    prop = getattr(article, "rd_proposable_area", "") or ""
    if prop:
        parts.append(prop)
    return " ".join(parts)


def has_investment_signal(article: RawArticle | FilteredArticle | SummarizedArticle) -> bool:
    return bool(_INVESTMENT_SIGNAL.search(_combined_text(article)))


def investment_signal_score(article: RawArticle | FilteredArticle | SummarizedArticle) -> int:
    text = _combined_text(article)
    score = 0
    if _INVESTMENT_SIGNAL.search(article.title):
        score += 40
    if _INVESTMENT_SIGNAL.search(text):
        score += 20
    if _KOREA_HINT.search(text):
        score += 15
    rd = getattr(article, "rd_match_score", 0) or 0
    score += rd * 10
    return score


def _extract_step_content(step: str, label: str) -> str:
    pattern = re.compile(rf"^\*\*{re.escape(label)}:\*\*\s*", re.I)
    return pattern.sub("", step.strip()).strip()


def parse_rd_fields(ko_summary_steps: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for step in ko_summary_steps:
        for label, key in _RD_HEADING_LABELS:
            if re.search(rf"^\*\*{re.escape(label)}:\*\*", step, re.I):
                content = _extract_step_content(step, label)
                if content:
                    fields[key] = content
                break
    return fields


def is_domestic_rd_target(investment_actor: str) -> bool:
    actor = investment_actor.strip()
    if not actor:
        return False
    if any(marker in actor for marker in _FOREIGN_ONLY_MARKERS):
        return False
    if _KOREA_HINT.search(actor):
        return True
    if re.search(r"해당\s*없음|N/A|not\s*applicable", actor, re.I):
        return False
    return False


def _fraunhofer_base_rd_score(article: SummarizedArticle) -> int:
    """Cooperation/R&D-commission angle only (LLM or heuristic)."""
    if is_excluded_rd_news(article):
        return 0

    stored = getattr(article, "rd_match_score", 0) or 0
    if stored:
        return max(0, min(5, int(stored)))

    fields = parse_rd_fields(article.ko_summary_steps)
    actor = fields.get("investment_actor", "")
    pain = fields.get("pain_point", "")
    score = 0

    if has_investment_signal(article):
        score += 1
    if is_domestic_rd_target(actor):
        score += 2
    if pain and "보류" not in pain and "부족" not in pain:
        score += 1
    if article.rd_proposable_area and article.rd_proposable_area not in ("해당 없음", ""):
        score += 1

    return max(0, min(5, score))


def compute_rd_match_score(
    article: SummarizedArticle,
    top_keywords: list[str] | None = None,
    *,
    monthly: bool = False,
) -> int:
    """Return R&D suitability 0–5: Fraunhofer cooperation + top-3 keyword relevance."""
    base = _fraunhofer_base_rd_score(article)
    if not top_keywords:
        return base

    if monthly:
        relevance = classify_monthly_context_relevance(article, top_keywords)
    else:
        from src.daily_report import classify_keyword_relevance

        relevance = classify_keyword_relevance(article, top_keywords)
    adjusted = base + _KEYWORD_RD_DELTA.get(relevance, -1)
    cap = _KEYWORD_RD_CAP.get(relevance, 3)
    return max(0, min(5, min(adjusted, cap)))


def build_rd_targeting_block(
    article: SummarizedArticle,
    top_keywords: list[str] | None = None,
) -> list[str]:
    if is_excluded_rd_news(article):
        return []

    fields = parse_rd_fields(article.ko_summary_steps)
    if not fields:
        return []

    score = compute_rd_match_score(article, top_keywords)
    label_map = {
        "investment_actor": "투자 주체",
        "investment_purpose": "투자 목적",
        "pain_point": "위탁 연구 니즈",
        "approach_strategy": "접근 전략",
    }
    lines = [
        f"- **R&D 적합도:** {score}/5",
        "- **R&D 타겟팅 (프라운호퍼):**",
    ]
    prop = polish_rd_field(article.rd_proposable_area or "")
    if prop and prop not in ("해당 없음", "명시 없음"):
        lines.append(f"  - **제안 R&D 영역:** {prop}")
    fact = (article.rd_fact_basis or "").strip()
    if fact and fact not in ("명시 없음", ""):
        lines.append(f"  - **팩트 근거:** {fact}")
    for key, label in label_map.items():
        value = fields.get(key, "").strip()
        if value:
            if key == "approach_strategy":
                value = _display_rd_field(value)
            lines.append(f"  - **{label}:** {value}")
    return lines if len(lines) > 2 else []


def build_daily_rd_insights(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None = None,
) -> list[str]:
    """Aggregate domestic R&D targeting signals for the daily executive summary."""
    kws = " · ".join((top_keywords or [])[:3]) or "(미설정)"
    domestic: list[tuple[int, SummarizedArticle, dict[str, str]]] = []

    for article in articles:
        fields = parse_rd_fields(article.ko_summary_steps)
        actor = fields.get("investment_actor", "")
        if not is_domestic_rd_target(actor):
            continue
        domestic.append((compute_rd_match_score(article, top_keywords), article, fields))

    if not domestic:
        return [
            "",
            f"**국내 R&D 타겟 시사점 (프라운호퍼 · {kws}):**",
            "",
            "- 당일 수집 항목 중 **국내 투자 주체**가 명시된 팩트 기반 타겟은 없음.",
            "",
        ]

    domestic.sort(key=lambda row: (-row[0], row[1].title.lower()))
    lines = [
        "",
        f"**국내 R&D 타겟 시사점 (프라운호퍼 · {kws}):**",
        "",
    ]
    for score, article, fields in domestic[:5]:
        actor = fields.get("investment_actor", "").strip()
        purpose = fields.get("investment_purpose", "").strip()
        pain = fields.get("pain_point", "").strip()
        strategy = fields.get("approach_strategy", "").strip()
        bullet = f"- **[{score}/5] {actor}**"
        if purpose:
            bullet += f" — 목적: {purpose}"
        if pain and "보류" not in pain and "부족" not in pain:
            bullet += f" | 니즈: {pain}"
        if strategy and "보류" not in strategy:
            bullet += f" | 접근: {_display_rd_field(strategy)}"
        title_short = article.title if len(article.title) <= 48 else f"{article.title[:48]}…"
        bullet += f" ([{title_short}]({article.url}))"
        lines.append(bullet)

    lines.append("")
    return lines


def _rd_context_blob(article: SummarizedArticle) -> str:
    """Fraunhofer proposal fields only — avoids false positives from generic summaries."""
    fields = parse_rd_fields(article.ko_summary_steps)
    return " ".join(
        [
            article.rd_proposable_area or "",
            fields.get("pain_point", ""),
            fields.get("investment_purpose", ""),
        ]
    )


def classify_monthly_context_relevance(
    article: SummarizedArticle,
    top_keywords: list[str] | None = None,
) -> str:
    """Monthly relevance: Fraunhofer proposal alignment first, then daily keyword fit."""
    focus_blob = _rd_context_blob(article)
    kws = top_keywords or []
    hits = [kw for kw in kws if kw and kw in focus_blob]
    power_hits = bool(_CONTEXT_POWER_HINT.search(focus_blob))

    if len(hits) >= 2 or (len(hits) == 1 and power_hits):
        return "direct"
    if hits or power_hits:
        return "indirect"

    fields = parse_rd_fields(article.ko_summary_steps)
    if is_domestic_rd_target(fields.get("investment_actor", "")):
        return "weak"

    from src.daily_report import classify_keyword_relevance

    return classify_keyword_relevance(article, top_keywords)


def monthly_context_priority(
    article: SummarizedArticle,
    top_keywords: list[str] | None = None,
) -> tuple[int, int, int, int]:
    """Sort key: higher R&D score, tighter keyword fit, stronger gov/R&D signals first."""
    relevance = classify_monthly_context_relevance(article, top_keywords)
    return (
        compute_rd_match_score(article, top_keywords, monthly=True),
        -_RELEVANCE_RANK.get(relevance, 3),
        gov_target_score(article),
        investment_signal_score(article),
    )


def prepare_logs_for_monthly_rd(
    logs: list[dict],
    *,
    min_score: int | None = None,
    top_keywords: list[str] | None = None,
) -> tuple[list[dict], int]:
    """Filter monthly logs to R&D match score >= min_score (default 4)."""
    from src.daily_report import log_to_summarized_article, prepare_logs_for_monthly

    threshold = min_score if min_score is not None else MONTHLY_RD_MIN_SCORE
    eligible, _ = prepare_logs_for_monthly(logs)
    rd_logs: list[dict] = []
    excluded = 0

    for log in eligible:
        article = log_to_summarized_article(log)
        base = _fraunhofer_base_rd_score(article)
        if base >= threshold:
            rd_logs.append(
                {
                    **log,
                    "rd_match_score": compute_rd_match_score(
                        article, top_keywords, monthly=True
                    ),
                }
            )
        else:
            excluded += 1

    def _sort_key(row: dict) -> tuple:
        article = log_to_summarized_article(row)
        rd, rel, gov, inv = monthly_context_priority(article, top_keywords)
        return (-rd, rel, -gov, -inv, row.get("log_date", ""))

    rd_logs.sort(key=_sort_key)
    return rd_logs, excluded
