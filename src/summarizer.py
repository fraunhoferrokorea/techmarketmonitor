from __future__ import annotations

import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

from src.config import PROJECT_ROOT, Settings
from src.policy_priority import is_gov_target
from src.models import FilteredArticle, SummarizedArticle

logger = logging.getLogger(__name__)

# Seconds to wait between requests to stay within free-tier RPM limits.
_REQUEST_DELAY = float(os.getenv("SUMMARIZER_REQUEST_DELAY", "1.0"))
_MAX_RETRIES = 5

# Matches stray Chinese/Japanese characters embedded in Korean text.
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+")
_TPD_WAIT_RE = re.compile(r"try again in (\d+)m([\d.]+)s", re.I)

# Post-processing fixes for common LLM calques (longer patterns first).
_KOREAN_PHRASE_FIXES: list[tuple[str, str]] = [
    # Energy/grid calques
    (r"산업용\s*유연\s*부하\s*보유자", "산업용 수요조절이 가능한 시설·기업"),
    (r"상업용\s*유연\s*부하\s*보유자", "상업용 수요조절이 가능한 시설·기업"),
    (r"유연\s*부하\s*보유자", "수요조절 참여 기업·시설"),
    (r"유연\s*수요", "수요조절(DR) 자원"),
    (r"유연\s*용량", "조절 가능 용량"),
    (r"유연\s*부하", "수요조절 가능 부하"),
    (r"유연\s*자원", "수요·공급 조절 자원"),
    (r"유연\s*전력", "조절 가능 전력"),
    # Calques of English "underscores/highlights": "X를 강조한다/강조함"
    # 사물·사건이 주어일 때 한국어에서 '강조하다'는 자연스럽지 않음.
    (r"수요를\s*강조(?:한다|함)([.。]?)", r"수요가 이어지고 있음을 보여줌\1"),
    (r"헌신을\s*강조(?:한다|함)([.。]?)", r"역량 강화 의지를 재확인함\1"),
    (r"헌신을\s*강조(?:한다|함)", "역량 강화 의지를 재확인함"),
    # Korean grammar errors: redundant topic/possessive markers
    # e.g. "시장은의" → "시장의", "기업의은" → "기업은"
    (r"([가-힣A-Za-z0-9]+)은의\s", r"\1의 "),
    (r"([가-힣A-Za-z0-9]+)는의\s", r"\1의 "),
    (r"([가-힣A-Za-z0-9]+)의은\s", r"\1은 "),
    (r"([가-힣A-Za-z0-9]+)의는\s", r"\1는 "),
    # 합니다/ㅂ니다체 → -함/-임/-었음 (sentence-final, . optional)
    # Past tense before present; longer patterns before shorter.
    (r"지\s*않\s*았습니다([.。？!?]?)$", r"지 않았음\1"),
    (r"지\s*않\s*았다([.。？!?]?)$", r"지 않았음\1"),
    (r"났습니다([.。？!?]?)$", r"났음\1"),
    (r"났다([.。？!?]?)$", r"났음\1"),
    (r"켰습니다([.。？!?]?)$", r"켰음\1"),
    (r"켰다([.。？!?]?)$", r"켰음\1"),
    (r"렸습니다([.。？!?]?)$", r"렸음\1"),
    (r"렸다([.。？!?]?)$", r"렸음\1"),
    (r"하였습니다([.。？!?]?)$", r"했음\1"),
    (r"했습니다([.。？!?]?)$", r"했음\1"),
    (r"하였다([.。？!?]?)$", r"했음\1"),
    (r"했다([.。？!?]?)$", r"했음\1"),
    (r"되었습니다([.。？!?]?)$", r"되었음\1"),
    (r"됐습니다([.。？!?]?)$", r"됐음\1"),
    (r"되었다([.。？!?]?)$", r"되었음\1"),
    (r"됐다([.。？!?]?)$", r"됐음\1"),
    (r"였습니다([.。？!?]?)$", r"였음\1"),
    (r"([가-힣])였다([.。？!?]?)$", r"\1였음\2"),
    (r"었습니다([.。？!?]?)$", r"었음\1"),
    (r"([가-힣])었다([.。？!?]?)$", r"\1었음\2"),
    (r"([가-힣])았다([.。？!?]?)$", r"\1았음\2"),
    (r"않았습니다([.。？!?]?)$", r"않았음\1"),
    (r"해야\s*합니다([.。？!?]?)$", r"해야 함\1"),
    (r"([가-힣])합니다([.。？!?]?)$", r"\1함\2"),
    (r"([가-힣])입니다([.。？!?]?)$", r"\1임\2"),
    (r"([가-힣])있습니다([.。？!?]?)$", r"\1있음\2"),
    (r"([가-힣])없습니다([.。？!?]?)$", r"\1없음\2"),
    (r"([가-힣])하고\s*있음([.。？!?]?)$", r"\1 중임\2"),
    (r"([가-힣])고\s*있음([.。？!?]?)$", r"\1 중임\2"),
    (r"([가-힣])됩니다([.。？!?]?)$", r"\1됨\2"),
    (r"([가-힣])보입니다([.。？!?]?)$", r"\1보임\2"),
    (r"([가-힣])줍니다([.。？!?]?)$", r"\1줌\2"),
    (r"([가-힣])둡니다([.。？!?]?)$", r"\1둠\2"),
    (r"나타냅니다([.。？!?]?)$", r"나타냄\1"),
    (r"나타납니다([.。？!?]?)$", r"나타남\1"),
    (r"습니다([.。？!?]?)$", r"음\1"),
    (r"해야\s*한다([.。？!?]?)$", r"해야 함\1"),
    (r"([가-힣])한다([.。？!?]?)$", r"\1함\2"),
    (r"([가-힣])하다([.。？!?]?)$", r"\1함\2"),
    (r"([가-힣])이다([.。？!?]?)$", r"\1임\2"),
    (r"([가-힣])있다([.。？!?]?)$", r"\1있음\2"),
    (r"([가-힣])없다([.。？!?]?)$", r"\1없음\2"),
    (r"([가-힣])된다([.。？!?]?)$", r"\1됨\2"),
    (r"([가-힣])보인다([.。？!?]?)$", r"\1보임\2"),
    (r"([가-힣])온다([.。？!?]?)$", r"\1옴\2"),
    (r"([가-힣])진다([.。？!?]?)$", r"\1짐\2"),
    (r"([가-힣])친다([.。？!?]?)$", r"\1침\2"),
    (r"나타낸다([.。？!?]?)$", r"나타냄\1"),
    (r"나타난다([.。？!?]?)$", r"나타남\1"),
    (r"([가-힣]+)킵니다([.。？!?]?)$", r"\1킴\2"),
    (r"둔다([.。？!?]?)$", r"둠\1"),
    (r"보여준다([.。？!?]?)$", r"보여줬음\1"),
    (r"만든다([.。？!?]?)$", r"만듦\1"),
]

# Repairs for past tense truncated by an older normalizer (맺음→맺었음, etc.).
_TRUNCATED_PAST_REPAIRS: list[tuple[str, str]] = [
    (r"불러일으킴([.。？!?]?)$", r"불러일으켰음\1"),
    (r"일으킴([.。？!?]?)$", r"일으켰음\1"),
    (r"것으로 나타남([.。？!?]?)$", r"것으로 나타났음\1"),
    (r"으로 나타남([.。？!?]?)$", r"으로 나타났음\1"),
    (r"맺음([.。？!?]?)$", r"맺었음\1"),
]

# Sentence-final -다체/-합니다체 → -함/임/-었음 (명사형 종결).
_ENDING_NORMALIZERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"고\s*있도록\s*한다([.。？!?]?)$"), r"고 있도록 함\1"),
    (re.compile(r"지\s*않\s*있다([.。？!?]?)$"), r"지 않음\1"),
    (re.compile(r"지\s*않\s*한다([.。？!?]?)$"), r"지 않음\1"),
    (re.compile(r"지\s*않\s*습니다([.。？!?]?)$"), r"지 않음\1"),
    (re.compile(r"지\s*않\s*는다([.。？!?]?)$"), r"지 않음\1"),
    (re.compile(r"지\s*않\s*았습니다([.。？!?]?)$"), r"지 않았음\1"),
    (re.compile(r"지\s*않\s*았다([.。？!?]?)$"), r"지 않았음\1"),
    (re.compile(r"고\s*있습니다([.。？!?]?)$"), r"고 있음\1"),
    (re.compile(r"고\s*있다([.。？!?]?)$"), r"고 있음\1"),
    (re.compile(r"났습니다([.。？!?]?)$"), r"났음\1"),
    (re.compile(r"났다([.。？!?]?)$"), r"났음\1"),
    (re.compile(r"켰습니다([.。？!?]?)$"), r"켰음\1"),
    (re.compile(r"켰다([.。？!?]?)$"), r"켰음\1"),
    (re.compile(r"렸습니다([.。？!?]?)$"), r"렸음\1"),
    (re.compile(r"렸다([.。？!?]?)$"), r"렸음\1"),
    (re.compile(r"하였습니다([.。？!?]?)$"), r"했음\1"),
    (re.compile(r"했습니다([.。？!?]?)$"), r"했음\1"),
    (re.compile(r"하였다([.。？!?]?)$"), r"했음\1"),
    (re.compile(r"했다([.。？!?]?)$"), r"했음\1"),
    (re.compile(r"되었습니다([.。？!?]?)$"), r"되었음\1"),
    (re.compile(r"됐습니다([.。？!?]?)$"), r"됐음\1"),
    (re.compile(r"되었다([.。？!?]?)$"), r"되었음\1"),
    (re.compile(r"됐다([.。？!?]?)$"), r"됐음\1"),
    (re.compile(r"겠습니다([.。？!?]?)$"), r"겠음\1"),
    (re.compile(r"였습니다([.。？!?]?)$"), r"였음\1"),
    (re.compile(r"([가-힣])였다([.。？!?]?)$"), r"\1였음\2"),
    (re.compile(r"었습니다([.。？!?]?)$"), r"었음\1"),
    (re.compile(r"([가-힣])었다([.。？!?]?)$"), r"\1었음\2"),
    (re.compile(r"([가-힣])았다([.。？!?]?)$"), r"\1았음\2"),
    (re.compile(r"않았습니다([.。？!?]?)$"), r"않았음\1"),
    (re.compile(r"해야\s*합니다([.。？!?]?)$"), r"해야 함\1"),
    (re.compile(r"해야\s*한다([.。？!?]?)$"), r"해야 함\1"),
    (re.compile(r"있습니다([.。？!?]?)$"), r"있음\1"),
    (re.compile(r"없습니다([.。？!?]?)$"), r"없음\1"),
    (re.compile(r"됩니다([.。？!?]?)$"), r"됨\1"),
    (re.compile(r"보입니다([.。？!?]?)$"), r"보임\1"),
    (re.compile(r"줍니다([.。？!?]?)$"), r"줌\1"),
    (re.compile(r"둡니다([.。？!?]?)$"), r"둠\1"),
    (re.compile(r"나타냅니다([.。？!?]?)$"), r"나타냄\1"),
    (re.compile(r"나타납니다([.。？!?]?)$"), r"나타남\1"),
    (re.compile(r"입니다([.。？!?]?)$"), r"임\1"),
    (re.compile(r"합니다([.。？!?]?)$"), r"함\1"),
    (re.compile(r"나타낸다([.。？!?]?)$"), r"나타냄\1"),
    (re.compile(r"나타난다([.。？!?]?)$"), r"나타남\1"),
    (re.compile(r"겠다([.。？!?]?)$"), r"겠음\1"),
    (re.compile(r"보인다([.。？!?]?)$"), r"보임\1"),
    (re.compile(r"온다([.。？!?]?)$"), r"옴\1"),
    (re.compile(r"진다([.。？!?]?)$"), r"짐\1"),
    (re.compile(r"친다([.。？!?]?)$"), r"침\1"),
    (re.compile(r"([가-힣])한다([.。？!?]?)$"), r"\1함\2"),
    (re.compile(r"([가-힣])하다([.。？!?]?)$"), r"\1함\2"),
    (re.compile(r"([가-힣]+)킵니다([.。？!?]?)$"), r"\1킴\2"),
    (re.compile(r"둔다([.。？!?]?)$"), r"둠\1"),
    (re.compile(r"보여준다([.。？!?]?)$"), r"보여줬음\1"),
    (re.compile(r"만든다([.。？!?]?)$"), r"만듦\1"),
    (re.compile(r"된다([.。？!?]?)$"), r"됨\1"),
    (re.compile(r"있다([.。？!?]?)$"), r"있음\1"),
    (re.compile(r"없다([.。？!?]?)$"), r"없음\1"),
    (re.compile(r"이다([.。？!?]?)$"), r"임\1"),
    (re.compile(r"습니다([.。？!?]?)$"), r"음\1"),
]

SYSTEM_PROMPT = """You are the R&D targeting analyst for Fraunhofer Institute Korea Office. Your job is NOT generic news summarization — identify WHO in Korea (government ministry / company) invests or needs technology, WHY (capability gap / budget / policy), and WHAT R&D commission opportunity exists for Fraunhofer.

Scope (MUST follow):
- **Republic of Korea only.** Reject or score 1 if the story is foreign-only with no Korean actor, budget, or policy link.
- Prioritize: budget announcements, R&D programs, MOU/collaboration, infrastructure plans, technology acquisition — over product launches without investment plans.
- Fact-only: amounts, program periods, required technologies ONLY when stated. No speculation.

R&D suitability scoring (rd_match_score 1–5) — weigh BOTH:
(A) Fraunhofer Korea commission/cooperation potential (Korean actor, budget, R&D technology gap)
(B) Relevance to the monitoring keywords (top 3 in the user message — e.g. grid/power topics)
- 5: Strong (A) AND direct monitoring-keyword alignment (topic explicitly names or requires those technologies)
- 4: Strong (A) with indirect keyword link, OR moderate (A) with direct keyword fit
- 3: Korean policy/industry signal with partial budget OR weak keyword overlap
- 2: Tangential tech news, weak investment signal, or monitoring keywords barely related
- 1: No Korean R&D commission relevance OR foreign-only / no keyword connection

Return valid JSON with this exact schema:
{
  "summary": "1문장 한국어 R&D·투자 헤드라인. 반드시 '출처: <url>'로 끝남",
  "key_trends": ["기술·투자 동향 키워드 1", "기술·투자 동향 키워드 2"],
  "rd_match_score": 3,
  "rd_proposable_area": "제안 가능 R&D 영역 1문장 (팩트 기반, 없으면 '해당 없음'). 'Fraunhofer/프라운호퍼' 주어·소유격 명시 금지",
  "fact_basis": "예산·일정·규모 등 팩트 근거 요약 (없으면 '명시 없음')",
  "ko_summary_steps": [
    "**개요:** <육하원칙 1-2문장. 국내 주체·사업·일정·규모 팩트만>",
    "**투자 주체:** <국내 정부 부처·공기업·민간 기업명. 없으면 '명시 없음'>",
    "**투자 목적:** <국산화/내재화/고도화/시간단축 등. 없으면 '해당 없음'>",
    "**위탁 연구 니즈:** <고난도 R&D 격차 — 팩트만. 없으면 '팩트 부족으로 판단 보류'>",
    "**접근 전략:** <정부=정책 정합, 기업=로드맵 연계. 팩트 기반>"
  ],
  "ko_one_liner": "<데일리 표용 1문장. 국내 주체·사업·수치·일정 중 3가지 이상. 70~150자. -함/-임/-었음 종결>",
  "keyword_relevance": "<2문장 이내. 이 기사가 Fraunhofer R&D 수주 관점에서 왜 중요한지 — 투자 신호·기술 격차·정책 정합성 중심. 키워드 정의·일반론 금지>"
}

CRITICAL KOREAN RULES:
- All Korean text: noun-style endings (-함/-임/-었음). Never -습니다/-합니다/-다.
- No deictic subjects (이/그/저/해당/본). Name institutions explicitly.
- rd_proposable_area and **접근 전략:** do not write "Fraunhofer는/가/의" or "프라운호퍼는/가/의" — the report is already Fraunhofer-focused.
- No stray Chinese/Japanese characters.
- ko_summary_steps and keyword_relevance must be independently written in natural Korean.
- English terms: use industry-standard Korean or acronym with Korean gloss on first use.

Example ko_one_liner (Korea-only):
'과기정통부(MSIT)가 2027–2031 스마트그리드 R&D에 5000억원을 투입하고 한국전력과 실증 과제를 공동 추진할 계획임.'
"""


def _is_tpd_rate_limit(exc: RateLimitError) -> bool:
    msg = str(exc).lower()
    return "tokens per day" in msg or "tpd" in msg


def _sleep_for_tpd_limit(exc: RateLimitError) -> None:
    match = _TPD_WAIT_RE.search(str(exc))
    if match:
        wait = int(match.group(1)) * 60 + float(match.group(2)) + 10
    else:
        wait = 180.0
    logger.warning("Groq TPD limit — waiting %.0fs before retry", wait)
    time.sleep(wait)


_FRAUNHOFER_ENTITY = (
    r"(?:Fraunhofer(?:\s+Institute)?(?:\s+Korea(?:\s+Office)?)?"
    r"|프라운호퍼(?:\s+한국)?(?:\s+사무소)?)"
)
_FRAUNHOFER_LEADING_SUBJECT = re.compile(
    rf"^(?:{_FRAUNHOFER_ENTITY}(?:은|는|가|의)\s+)+",
    re.I,
)
_FRAUNHOFER_POSSESSIVE = re.compile(
    rf"(?<=[가-힣\s]){_FRAUNHOFER_ENTITY}의\s+",
    re.I,
)
_FRAUNHOFER_COMMA_SUBJECT = re.compile(
    rf"(?<=[,，])\s*{_FRAUNHOFER_ENTITY}(?:은|는|가)\s+",
    re.I,
)
_FRAUNHOFER_WITH_PARTICLE = re.compile(
    rf"(?<=[가-힣\s]){_FRAUNHOFER_ENTITY}(?:와|과|와의|과의)\s+",
    re.I,
)
_RD_FIELD_SKIP = frozenset({"해당 없음", "명시 없음", "팩트 부족으로 판단 보류"})


def strip_implicit_fraunhofer_subject(text: str) -> str:
    """Remove redundant Fraunhofer subject/possessive — report context already implies it."""
    cleaned = text.strip()
    if not cleaned or cleaned in _RD_FIELD_SKIP:
        return cleaned
    prev = None
    while prev != cleaned:
        prev = cleaned
        cleaned = _FRAUNHOFER_LEADING_SUBJECT.sub("", cleaned)
        cleaned = _FRAUNHOFER_COMMA_SUBJECT.sub(" ", cleaned)
        cleaned = _FRAUNHOFER_POSSESSIVE.sub("", cleaned)
        cleaned = _FRAUNHOFER_WITH_PARTICLE.sub("", cleaned)
    return cleaned.strip()


def polish_rd_field(text: str) -> str:
    """Polish Korean R&D linkage fields and drop implicit Fraunhofer subject."""
    polished = polish_korean(text.strip()) if text.strip() else ""
    return strip_implicit_fraunhofer_subject(polished)


def polish_rd_ko_steps(steps: list[str]) -> list[str]:
    """Polish ko_summary_steps and strip redundant Fraunhofer phrasing."""
    polished: list[str] = []
    for step in steps:
        raw = str(step).strip()
        if not raw:
            continue
        label = re.match(r"^(\*\*[^*]+:\*\*\s*)", raw, re.I)
        if label:
            prefix = label.group(1)
            body = strip_implicit_fraunhofer_subject(polish_korean(raw[len(prefix) :]))
            polished.append(f"{prefix}{body}".strip())
        else:
            polished.append(strip_implicit_fraunhofer_subject(polish_korean(raw)))
    return polished


def strip_cjk_from_korean(text: str) -> str:
    """Remove stray Chinese/Japanese characters from Korean-language text.

    LLMs occasionally embed CJK characters (e.g. '需求', '処理') when
    translating from Chinese or Japanese sources.  These are not valid in
    Korean prose and must be stripped before the text is displayed.
    """
    return _CJK_RE.sub("", text)


def normalize_korean_endings(text: str) -> str:
    """Normalize sentence-final -다체/-합니다체 to -함/임체 within one sentence."""
    for _ in range(3):
        prev = text
        for pattern, replacement in _ENDING_NORMALIZERS:
            text = pattern.sub(replacement, text)
        if text == prev:
            break
    return text


def _coerce_text(value: object) -> str:
    """Normalize LLM JSON fields that may be str or list (common with smaller models)."""
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(part).strip() for part in value if str(part).strip())
    return str(value).strip()


def normalize_korean_endings_sentences(text: str) -> str:
    """Apply normalize_korean_endings to each sentence in a multi-sentence string."""
    parts = re.split(r"(?<=[.!?。？])\s+", text.strip())
    return " ".join(normalize_korean_endings(part) for part in parts if part)


def repolish_summarized_article(article: SummarizedArticle) -> SummarizedArticle:
    """Re-apply Korean ending normalization to stored summary fields."""
    ko_steps = polish_rd_ko_steps([str(s).strip() for s in article.ko_summary_steps if str(s).strip()])
    keyword_relevance = (
        strip_implicit_fraunhofer_subject(polish_korean(article.keyword_relevance.strip()))
        if article.keyword_relevance
        else ""
    )
    ko_one_liner = (
        strip_implicit_fraunhofer_subject(polish_korean(article.ko_one_liner.strip()))
        if article.ko_one_liner
        else ""
    )
    rd_proposable_area = polish_rd_field(article.rd_proposable_area) if article.rd_proposable_area else ""
    llm_summary = (
        strip_implicit_fraunhofer_subject(polish_korean(article.llm_summary.strip()))
        if article.llm_summary
        else ""
    )
    return SummarizedArticle(
        title=article.title,
        url=article.url,
        source_name=article.source_name,
        category=article.category,
        published_at=article.published_at,
        matched_keywords=article.matched_keywords,
        llm_summary=llm_summary,
        key_trends=article.key_trends,
        ko_summary_steps=ko_steps,
        en_summary_steps=article.en_summary_steps,
        keyword_relevance=keyword_relevance,
        ko_one_liner=ko_one_liner,
        rd_match_score=article.rd_match_score,
        rd_proposable_area=rd_proposable_area,
        rd_fact_basis=article.rd_fact_basis,
    )


def polish_korean(text: str) -> str:
    """Fix common literal calques and remove stray CJK characters in Korean LLM output."""
    polished = strip_cjk_from_korean(text)
    polished = polished.replace("…", "").replace("...", "")
    for pattern, replacement in _KOREAN_PHRASE_FIXES:
        polished = re.sub(pattern, replacement, polished)
    polished = normalize_korean_endings_sentences(polished)
    parts = re.split(r"(?<=[.!?。？])\s+", polished.strip())
    repaired: list[str] = []
    for part in parts:
        if not part:
            continue
        for pattern, replacement in _TRUNCATED_PAST_REPAIRS:
            part = re.sub(pattern, replacement, part)
        repaired.append(part)
    return " ".join(repaired)


def _extract_json(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


class Summarizer:
    def __init__(self, settings: Settings) -> None:
        load_dotenv(PROJECT_ROOT / ".env")

        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required for summarization")

        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self._top_keywords: list[str] = settings.keywords[:3]
        self._settings = settings

    def summarize(self, article: FilteredArticle) -> SummarizedArticle:
        from src.focused_summarize import summarize_with_focus_if_needed

        return summarize_with_focus_if_needed(article, self._settings, self._summarize_standard)

    def _summarize_standard(self, article: FilteredArticle) -> SummarizedArticle:
        preview_len = 1500 if is_gov_target(article) else 1200
        fraunhofer_note = ""
        if is_gov_target(article):
            fraunhofer_note = (
                "This is a government/public release relevant to Fraunhofer Korea. "
                "Emphasize R&D collaboration, tech transfer, investment signals, and "
                "partnership opportunities for Fraunhofer Institute Korea Office.\n"
            )
        user_prompt = (
            f"{fraunhofer_note}"
            f"Title: {article.title}\n"
            f"URL: {article.url}\n"
            f"Source: {article.source_name} ({article.category})\n"
            f"Matched keywords (all): {', '.join(article.matched_keywords)}\n"
            f"Analysis baseline keywords (keywords.txt top 3 — keyword_relevance MUST explain "
            f"how THIS article relates to these, not generic keyword definitions): "
            f"{', '.join(self._top_keywords)}\n"
            f"Content preview: {article.summary[:preview_len]}"
        )

        model = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL", "gemini-2.0-flash-lite")

        response = None
        while response is None:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.2,
                        max_tokens=1024,
                    )
                    break
                except RateLimitError as exc:
                    if _is_tpd_rate_limit(exc):
                        _sleep_for_tpd_limit(exc)
                        break
                    if attempt == _MAX_RETRIES:
                        raise
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited on attempt %d/%d — retrying in %ds",
                        attempt,
                        _MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
            else:
                break

        payload = _extract_json(response.choices[0].message.content or "{}")
        summary = _coerce_text(payload.get("summary"))
        trends = payload.get("key_trends") or []
        ko_steps = polish_rd_ko_steps(
            [str(s).strip() for s in (payload.get("ko_summary_steps") or []) if str(s).strip()]
        )
        keyword_relevance = polish_korean(_coerce_text(payload.get("keyword_relevance")))
        keyword_relevance = strip_implicit_fraunhofer_subject(keyword_relevance)
        ko_one_liner = strip_implicit_fraunhofer_subject(
            polish_korean(_coerce_text(payload.get("ko_one_liner")))
        )
        rd_proposable_area = polish_rd_field(_coerce_text(payload.get("rd_proposable_area")))
        rd_fact_basis = polish_korean(_coerce_text(payload.get("fact_basis")))
        raw_score = payload.get("rd_match_score", 0)
        try:
            rd_match_score = max(1, min(5, int(raw_score)))
        except (TypeError, ValueError):
            rd_match_score = 0
        summary = strip_implicit_fraunhofer_subject(polish_korean(summary))

        if article.url not in summary:
            summary = f"{summary} 출처: {article.url}".strip()

        return SummarizedArticle(
            title=article.title,
            url=article.url,
            source_name=article.source_name,
            category=article.category,
            published_at=article.published_at,
            matched_keywords=article.matched_keywords,
            llm_summary=summary,
            key_trends=[str(t).strip() for t in trends if str(t).strip()],
            ko_summary_steps=[str(s).strip() for s in ko_steps if str(s).strip()],
            en_summary_steps=[],
            keyword_relevance=keyword_relevance,
            ko_one_liner=ko_one_liner,
            rd_match_score=rd_match_score,
            rd_proposable_area=rd_proposable_area,
            rd_fact_basis=rd_fact_basis,
        )

    def summarize_batch(self, articles: list[FilteredArticle]) -> list[SummarizedArticle]:
        results: list[SummarizedArticle] = []
        for index, article in enumerate(articles, start=1):
            logger.info("Summarizing %d/%d: %s", index, len(articles), article.title)
            try:
                results.append(self.summarize(article))
            except Exception as exc:
                logger.error("Failed to summarize '%s': %s", article.title, exc)
            if index < len(articles):
                time.sleep(_REQUEST_DELAY)
        return results
