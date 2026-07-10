from __future__ import annotations

import re

from src.models import FilteredArticle, RawArticle, SummarizedArticle

# Official government / public R&D sources (name substrings, lowercased).
_OFFICIAL_SOURCE_HINTS = (
    "과기정통부",
    "과기부",
    "산업통상",
    "산업부",
    "motir",
    "motie",
    "중소벤처",
    "중기부",
    "국토교통",
    "국토부",
    "기후에너지",
    "기후부",
    "환경부",
    "재정경제",
    "교육부",
    "보건복지",
    "국방부",
    "우주항공",
    "kasa",
    "kistep",
    "iitp",
    "kipo",
    "ketep",
    "keit",
    "kiat",
    "tipa",
    "kaia",
    "krit",
    "국가기술표준",
    "kats",
    "한국연구재단",
    "nrf",
    "etri",
    "pacst",
    "국가과학기술자문",
)

# National master plans and major policy frameworks.
_PLAN_TITLE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"국가\s*표준\s*기본\s*계획", re.I),
    re.compile(r"제\s*\d+\s*차\s*국가\s*표준", re.I),
    re.compile(r"국가\s*(?:AI|인공지능)\s*(?:표준|행동|추진|전략)", re.I),
    re.compile(r"과학\s*기술\s*(?:기본\s*)?계획", re.I),
    re.compile(r"R\s*&\s*D\s*(?:혁신|투자|기본)\s*계획", re.I),
    re.compile(r"(?:연구\s*개발|R&D)\s*(?:특구|투자|혁신)\s*계획", re.I),
    re.compile(r"(?:디지털|에너지|바이오|인공지능)\s*(?:전략|기본\s*계획|로드\s*맵|행동\s*계획)", re.I),
    re.compile(r"(?:중장기|국가)\s*(?:과학기술|연구개발)\s*계획", re.I),
    re.compile(r"표준\s*기본\s*계획", re.I),
    re.compile(r"(?:합동|부\s*[·・]\s*처\s*[·・]\s*청)\s*['\u2018]?\d", re.I),
]

# Fraunhofer Korea–relevant government announcements (beyond master plans).
_FRAUNHOFER_TARGET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"프라운호퍼|fraunhofer", re.I),
    re.compile(r"MOU|업무\s*협약|양해\s*각서|협력\s*양해", re.I),
    re.compile(r"공동\s*연구|협력\s*연구|산학\s*연|국제\s*공동", re.I),
    re.compile(r"기술\s*협력|기술\s*이전|실증\s*사업|시범\s*사업", re.I),
    re.compile(r"R\s*&\s*D|연구\s*개발|국책\s*과제|연구\s*사업", re.I),
    re.compile(r"사업\s*공고|지원\s*사업|R&D\s*투자|투자\s*계획", re.I),
    re.compile(r"표준\s*화|국제\s*표준|K-표준|인증|시험\s*평가|KOLAS", re.I),
    re.compile(r"혁신\s*성장|이노베이션|M\.?AX|제조\s*AI|AX\s", re.I),
    re.compile(r"에너지\s*전환|스마트\s*그리드|ESS|VPP|전력\s*망|전력\s*계통", re.I),
    re.compile(r"EU|Horizon|독일|한\s*[·・]\s*독|독\s*[·・]\s*한", re.I),
    re.compile(r"중소\s*기업|제조\s*혁신|산업\s*기술|기술\s*사업화", re.I),
    re.compile(r"IP|특허|기술\s*료|TRL|기술\s*수준", re.I),
]

_PLAN_BODY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"실행\s*과제", re.I),
    re.compile(r"\d+\s*대\s*전략", re.I),
    re.compile(r"국가표준\s*심의\s*회", re.I),
    re.compile(r"K-표준", re.I),
    re.compile(r"국제\s*표준\s*\d+[,\d]*\s*건", re.I),
]

_GOV_TARGET_PASS_LABEL = "정부·R&D 타깃"
# Backward-compatible alias used in older entries/tests.
_POLICY_PASS_LABEL = _GOV_TARGET_PASS_LABEL

# Domain gate for gov-target collection bypass: power / smart-grid / energy storage.
# Without these, official MOU·R&D·예산 releases (보건·고용·교육 등) are excluded.
_ENERGY_GRID_DOMAIN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"전력\s*계통|파워\s*그리드|스마트\s*그리드|전력망|송배전|배전\s*계통|"
        r"계통\s*안정|전력\s*품질|수요\s*반응|가상\s*발전|마이크로그리드",
        re.I,
    ),
    re.compile(
        r"\bBESS\b|\bESS\b|\bVPP\b|에너지|전력\s*저장|재생\s*에너지|신재생|"
        r"기후\s*에너지|전력\s*수급|전력\s*인프라|"
        r"한국전력|\bKEPCO\b|한전|전력\s*시장|전력\s*거래",
        re.I,
    ),
    re.compile(
        r"power\s*grid|smart\s*grid|microgrid|energy\s*storage|"
        r"power\s*system|grid\s*stability|transmission\s*grid|"
        r"distribution\s*grid|demand\s*response",
        re.I,
    ),
]


def _combined_text(article: RawArticle | FilteredArticle | SummarizedArticle) -> str:
    parts = [article.title, article.source_name]
    summary = getattr(article, "summary", None)
    if summary:
        parts.append(summary)
    return " ".join(parts)


def has_energy_grid_domain(
    article: RawArticle | FilteredArticle | SummarizedArticle,
) -> bool:
    """True when title/summary/source mentions power-grid / energy-storage domain."""
    return _matches_any(_ENERGY_GRID_DOMAIN_PATTERNS, _combined_text(article))


def passes_gov_collection_exception(
    article: RawArticle | FilteredArticle | SummarizedArticle,
) -> bool:
    """Gov-target may skip top-N core keywords only with energy/grid domain (or Fraunhofer)."""
    text = _combined_text(article)
    if re.search(r"프라운호퍼|fraunhofer", text, re.I):
        return True
    return is_gov_target(article) and has_energy_grid_domain(article)


def _is_official_source(article: RawArticle | FilteredArticle | SummarizedArticle) -> bool:
    blob = f"{article.source_name} {article.url}".lower()
    return any(h in blob for h in _OFFICIAL_SOURCE_HINTS) or ".go.kr" in blob


def _matches_any(patterns: list[re.Pattern[str]], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def is_fraunhofer_target_announcement(
    article: RawArticle | FilteredArticle | SummarizedArticle,
) -> bool:
    """Government/public release likely useful for Fraunhofer Korea (plans, MOU, R&D, standards)."""
    text = _combined_text(article)
    if _matches_any(_PLAN_TITLE_PATTERNS, text):
        return True
    if _matches_any(_FRAUNHOFER_TARGET_PATTERNS, article.title):
        return True
    if _is_official_source(article) and _matches_any(_FRAUNHOFER_TARGET_PATTERNS, text):
        return True
    if _is_official_source(article) and _matches_any(_PLAN_BODY_PATTERNS, text):
        return True
    return False


def is_gov_target(article: RawArticle | FilteredArticle | SummarizedArticle) -> bool:
    """Official-source item worth Fraunhofer-focused capture and summarization."""
    if not _is_official_source(article):
        return _matches_any(_PLAN_TITLE_PATTERNS, article.title) or bool(
            re.search(r"프라운호퍼|fraunhofer", article.title, re.I)
        )
    return is_fraunhofer_target_announcement(article)


# Backward-compatible name.
is_policy_priority = is_gov_target


def gov_target_score(article: RawArticle | FilteredArticle | SummarizedArticle) -> int:
    """Higher score = higher priority for Fraunhofer-focused monitoring."""
    text = _combined_text(article)
    score = 0

    if _matches_any(_PLAN_TITLE_PATTERNS, article.title):
        score += 100
    elif _matches_any(_PLAN_TITLE_PATTERNS, text):
        score += 80

    if re.search(r"프라운호퍼|fraunhofer", text, re.I):
        score += 90

    if _matches_any(_FRAUNHOFER_TARGET_PATTERNS, article.title):
        score += 50
    elif _matches_any(_FRAUNHOFER_TARGET_PATTERNS, text):
        score += 30

    if _is_official_source(article):
        score += 25
        if _matches_any(_PLAN_BODY_PATTERNS, text):
            score += 15

    if re.search(r"보도\s*자료|공식\s*발표|확정\s*발표|MOU|업무\s*협약", text, re.I):
        score += 10

    return score


policy_priority_score = gov_target_score


def gov_target_pass_label() -> str:
    return _GOV_TARGET_PASS_LABEL


def policy_pass_label() -> str:
    return gov_target_pass_label()


def is_official_government_source(
    article: RawArticle | FilteredArticle | SummarizedArticle,
) -> bool:
    return _is_official_source(article)


def is_plan_document(article: RawArticle | FilteredArticle | SummarizedArticle) -> bool:
    """Government master plan, basic plan, or primary source document (not a short press blurb)."""
    text = _combined_text(article)
    url = article.url.lower()
    if "expdocview" in url or "/archive/expdoc" in url:
        return True
    if "전문자료" in article.source_name:
        return True
    if _matches_any(_PLAN_TITLE_PATTERNS, article.title):
        return True
    if _matches_any(_PLAN_TITLE_PATTERNS, text):
        return True
    if re.search(r"\[첨부\s*(?:PDF|문서)\s*원문", text, re.I):
        return True
    return False
