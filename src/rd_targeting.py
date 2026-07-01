from __future__ import annotations

import re

from src.models import FilteredArticle, RawArticle, SummarizedArticle

# Articles with these signals are prioritized over pure technology news.
_INVESTMENT_SIGNAL = re.compile(
    r"투자|예산|협력|로드\s*맵|로드맵|기술\s*확보|"
    r"invest(?:ment|ing)?|budget|funding|road\s*map|collaborat|"
    r"M\s*&\s*A|인수|합병|R\s*&\s*D|연구\s*개발|위탁|사업\s*기간|"
    r"국산화|내재화|고도화",
    re.I,
)

_KOREA_HINT = re.compile(
    r"한국|대한민국|국내|Korea|Korean|서울|과기정통부|산업통상|"
    r"MOTIE|MSIT|IITP|KISTEP|ETRI|KAIST|삼성|SK|LG|현대|포스코|"
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


def build_rd_targeting_block(ko_summary_steps: list[str]) -> list[str]:
    fields = parse_rd_fields(ko_summary_steps)
    if not fields:
        return []

    label_map = {
        "investment_actor": "투자 주체",
        "investment_purpose": "투자 목적",
        "pain_point": "위탁 연구 니즈",
        "approach_strategy": "접근 전략",
    }
    lines = ["- **R&D 타겟팅 (프라운호퍼):**"]
    for key, label in label_map.items():
        value = fields.get(key, "").strip()
        if value:
            lines.append(f"  - **{label}:** {value}")
    return lines if len(lines) > 1 else []


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
        domestic.append((investment_signal_score(article), article, fields))

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
    for _, article, fields in domestic[:5]:
        actor = fields.get("investment_actor", "").strip()
        purpose = fields.get("investment_purpose", "").strip()
        pain = fields.get("pain_point", "").strip()
        strategy = fields.get("approach_strategy", "").strip()
        bullet = f"- **{actor}**"
        if purpose:
            bullet += f" — 목적: {purpose}"
        if pain and "보류" not in pain and "부족" not in pain:
            bullet += f" | 니즈: {pain}"
        if strategy and "보류" not in strategy:
            bullet += f" | 접근: {strategy}"
        title_short = article.title if len(article.title) <= 48 else f"{article.title[:48]}…"
        bullet += f" ([{title_short}]({article.url}))"
        lines.append(bullet)

    lines.append("")
    return lines
