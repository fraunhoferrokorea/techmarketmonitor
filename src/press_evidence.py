"""Press-release evidence: attest keywords and extract verbatim quotes.

Fact-check pipeline used by daily sanitization and monthly report generation:
1. Build / re-fetch government press corpus (HTML + attachments).
2. Attest which monitoring keywords actually appear in the corpus.
3. Extract short verbatim quotes around attested terms.
4. Reject theme/summary claims that dump unattested keyword lists.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_QUOTE_RADIUS = 90
_MAX_QUOTE_LEN = 220
_MAX_QUOTES = 3


@dataclass(frozen=True)
class PressEvidence:
    attested_keywords: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    source_chars: int = 0

    @property
    def has_quotes(self) -> bool:
        return bool(self.quotes)


def compact_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def normalize_match_key(text: str) -> str:
    return compact_whitespace(text).lower().replace(" ", "")


def keyword_in_source(keyword: str, source: str) -> bool:
    """True when *keyword* (or compact form) appears in source text."""
    needle = (keyword or "").strip()
    if not needle or not source:
        return False
    src = compact_whitespace(source)
    if needle in src:
        return True
    src_key = normalize_match_key(src)
    needle_key = normalize_match_key(needle)
    if needle_key and needle_key in src_key:
        return True
    # English case-insensitive
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\s\-_/]*", needle):
        return bool(re.search(re.escape(needle), src, re.I))
    return False


def attest_keywords(source: str, keywords: list[str]) -> list[str]:
    """Return monitoring keywords that are literally present in the press corpus."""
    attested: list[str] = []
    seen: set[str] = set()
    for raw in keywords:
        kw = (raw or "").strip()
        if not kw:
            continue
        key = normalize_match_key(kw)
        if key in seen:
            continue
        if keyword_in_source(kw, source):
            seen.add(key)
            attested.append(kw)
    return attested


def _quote_window(source: str, start: int, end: int, radius: int = _QUOTE_RADIUS) -> str:
    left = max(0, start - radius)
    right = min(len(source), end + radius)
    snippet = source[left:right].strip()
    if left > 0:
        snippet = "…" + snippet
    if right < len(source):
        snippet = snippet + "…"
    snippet = compact_whitespace(snippet)
    if len(snippet) > _MAX_QUOTE_LEN:
        snippet = snippet[: _MAX_QUOTE_LEN - 1].rstrip() + "…"
    return snippet


def find_verbatim_quote(source: str, needle: str, *, radius: int = _QUOTE_RADIUS) -> str | None:
    """Return one ellipsis-wrapped verbatim snippet containing *needle*."""
    text = compact_whitespace(source)
    term = (needle or "").strip()
    if not text or not term:
        return None
    idx = text.find(term)
    if idx < 0:
        # compact match (spaces removed) — map back approximately via regex of chars
        compact_src = normalize_match_key(text)
        compact_term = normalize_match_key(term)
        cidx = compact_src.find(compact_term) if compact_term else -1
        if cidx < 0 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\s\-_/]*", term):
            m = re.search(re.escape(term), text, re.I)
            if not m:
                return None
            return _quote_window(text, m.start(), m.end(), radius)
        if cidx < 0:
            return None
        # approximate index: walk original until compact length reaches cidx
        approx = 0
        compact_i = 0
        while approx < len(text) and compact_i < cidx:
            ch = text[approx]
            approx += 1
            if not ch.isspace():
                compact_i += 1
        end = approx
        needed = len(compact_term)
        taken = 0
        while end < len(text) and taken < needed:
            ch = text[end]
            end += 1
            if not ch.isspace():
                taken += 1
        return _quote_window(text, approx, end, radius)
    return _quote_window(text, idx, idx + len(term), radius)


def collect_press_evidence(
    source: str,
    keywords: list[str],
    *,
    max_quotes: int = _MAX_QUOTES,
) -> PressEvidence:
    """Attest keywords and collect up to *max_quotes* verbatim press quotes."""
    text = compact_whitespace(source)
    attested = attest_keywords(text, keywords)
    quotes: list[str] = []
    seen_q: set[str] = set()
    for kw in attested:
        quote = find_verbatim_quote(text, kw)
        if not quote:
            continue
        key = normalize_match_key(quote)
        if key in seen_q:
            continue
        seen_q.add(key)
        quotes.append(f"「{quote}」")
        if len(quotes) >= max_quotes:
            break
    return PressEvidence(
        attested_keywords=attested,
        quotes=quotes,
        source_chars=len(text),
    )


def format_evidence_basis(evidence: PressEvidence, fallback: str = "") -> str:
    """Build rd_fact_basis text preferring direct quotes."""
    if evidence.quotes:
        joined = " ".join(evidence.quotes)
        if evidence.attested_keywords:
            kws = " · ".join(evidence.attested_keywords[:6])
            return f"원문 인용({kws}): {joined}"
        return f"원문 인용: {joined}"
    fb = (fallback or "").strip()
    return fb if fb and fb not in {"명시 없음", "해당 없음"} else "명시 없음"


def strip_unattested_monitoring_keywords(
    text: str,
    monitoring_keywords: list[str],
    attested: set[str] | list[str],
) -> str:
    """Remove monitoring-keyword tokens from *text* unless attested in press."""
    if not text:
        return text
    attested_keys = {normalize_match_key(k) for k in attested}
    # longest first to avoid partial leftovers
    ordered = sorted(
        {(k or "").strip() for k in monitoring_keywords if (k or "").strip()},
        key=len,
        reverse=True,
    )
    result = text
    for kw in ordered:
        if normalize_match_key(kw) in attested_keys:
            continue
        if not keyword_in_source(kw, result):
            continue
        # remove keyword and adjacent separators
        pattern = re.compile(
            rf"(?:\s*[·,|/]\s*)?{re.escape(kw)}(?:\s*[·,|/]\s*)?",
            re.I,
        )
        result = pattern.sub(" ", result)
    result = re.sub(r"\s{2,}", " ", result)
    result = re.sub(r"\s*·\s*·\s*", " · ", result)
    result = re.sub(r"(?:^|\s)[·,/|]+(?:\s|$)", " ", result)
    return compact_whitespace(result)


def theme_intro_from_evidence(
    theme: str,
    actors: list[str],
    attested_keywords: list[str],
) -> str:
    """Fact-grounded theme lead — never dump the full monitoring keyword list."""
    clean_actors = [a.strip() for a in actors if (a or "").strip()]
    actor_text = ", ".join(clean_actors[:3]) if clean_actors else "국내 정부·공공기관"

    if attested_keywords:
        kw_label = " · ".join(attested_keywords[:8])
        return (
            f"당월 {actor_text} 보도자료 원문에서 {kw_label} 관련 표현이 확인됨. "
            f"아래 항목은 원문 인용 가능한 범위만 정리함."
        )

    generic = {
        "전력·그리드": (
            f"당월 {actor_text} 발표 중 모니터링 전력·그리드 키워드의 원문 직접 언급은 "
            f"제한적임. 보도자료에 명시된 에너지·전력 관련 표현만 정리함."
        ),
        "제조AI·스마트공장": (
            f"당월 {actor_text} 등이 제조AI·에이전트·데이터 관련 정책을 발표함. "
            f"원문에 나온 사업·금액·일정만 반영함."
        ),
        "표준·인증·보안": (
            f"당월 {actor_text} 등이 국가표준·인증 관련 조치를 발표함. "
            f"표준번호·시행일 등 원문 팩트만 반영함."
        ),
        "바이오·그린": (
            f"당월 {actor_text} 등이 바이오·그린 관련 기술이전·공동연구를 발표함. "
            f"원문에 명시된 범위만 정리함."
        ),
    }
    return generic.get(
        theme,
        f"당월 {actor_text} 등에서 국내 R&D·정책 신호가 확인됨. "
        f"원문 근거가 있는 항목만 반영함.",
    )


def looks_like_keyword_dump(text: str, monitoring_keywords: list[str], *, min_hits: int = 5) -> bool:
    """Detect summaries that paste many monitoring keywords (template hallucination)."""
    if not text:
        return False
    hits = sum(1 for kw in monitoring_keywords if keyword_in_source(kw, text))
    return hits >= min_hits


def fetch_press_corpus(url: str, title: str = "", source_name: str = "") -> str:
    """Re-fetch government press HTML + attachments for fact-checking."""
    if not (url or "").strip():
        return ""
    try:
        from datetime import datetime, timezone

        from src.article_enrichment import enrich_raw_article
        from src.models import RawArticle
        from src.policy_priority import is_official_government_source

        raw = RawArticle(
            title=title or url,
            url=url,
            summary="",
            source_name=source_name or "",
            category="korean",
            published_at=datetime.now(tz=timezone.utc),
        )
        # Force enrich path for gov URLs even with empty summary.
        if not is_official_government_source(raw) and ".go.kr" not in url.lower() and "korea.kr" not in url.lower():
            return ""
        enriched = enrich_raw_article(raw)
        return compact_whitespace(enriched.summary or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Press corpus fetch failed for %s: %s", url, exc)
        return ""
