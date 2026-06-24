from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from src.models import SummarizedArticle
from src.summarizer import polish_korean, strip_cjk_from_korean

logger = logging.getLogger(__name__)

_OUTPUT_BASE = Path(__file__).resolve().parent.parent / "output" / "daily"

_TIER1_NEWS = {"reuters", "bloomberg", "ap news", "associated press"}
_TIER1_RESEARCH = {"gartner", "idc", "mckinsey", "statista"}
_PEER_REVIEW_HINTS = {"ieee", "springer", "elsevier", "wiley", "nature", "science"}
_PREPRINT_HINTS = {"arxiv", "biorxiv", "medrxiv", "ssrn"}
_GOVERNMENT_HINTS = {
    "motie",
    "msit",
    "kistep",
    "iitp",
    "kipo",
    "europa.eu",
    "ec.europa.eu",
    "nist.gov",
    "gov.uk",
    ".go.kr",
    ".gov",
}

_TAG_RULES: list[tuple[str, str]] = [
    (r"invest|fund|series|valuation|펀딩|투자|유치", "#투자"),
    (r"acqui|merger|m&a|합병|인수|제휴", "#M&A"),
    (r"launch|release|출시|런칭|unveil", "#제품출시"),
    (r"regulat|policy|법안|규제|standard|표준|compliance", "#규제"),
    (r"market share|compet|경쟁|점유|vendor|leader", "#경쟁"),
    (r"market size|cagr|revenue|billion|million|시장.?규모|성장률", "#시장수치"),
    (r"risk|controvers|scandal|사고|논란|threat", "#리스크"),
    (r"forecast|outlook|predict|전망|analyst|애널리스트", "#전문가전망"),
    (r"research|study|paper|논문|experiment|method", "#논문"),
    (r"r&d|technology|tech|기술|innovation|algorithm", "#기술"),
    (r"company|enterprise|organi|workforce|실적|인력|전략", "#기업동향"),
]

_CATEGORY_MATERIAL_TYPE = {
    "academic": "논문",
    "tech_news": "기사",
    "enterprise": "기사",
    "energy": "기사",
    "semiconductor": "기사",
    "korean": "기사",
}


def save_daily_report(
    log_date: date,
    articles: list[SummarizedArticle],
    output_dir: Path | None = None,
    top_keywords: list[str] | None = None,
    recorder: str | None = None,
) -> Path | None:
    """Build and write a unified daily research log (Markdown)."""
    if not articles:
        logger.info("No articles to report for %s — skipping daily report", log_date)
        return None

    out_dir = output_dir or _OUTPUT_BASE
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = out_dir / f"daily_{log_date.isoformat()}.md"
    report_path.write_text(
        _build_markdown(log_date, articles, top_keywords, recorder),
        encoding="utf-8",
    )
    logger.info("Daily research log saved → %s", report_path)
    return report_path


def _material_type(article: SummarizedArticle) -> str:
    if article.category == "academic":
        return "논문"
    source = article.source_name.lower()
    if any(h in source for h in _TIER1_RESEARCH):
        return "보고서(시장조사)"
    if any(h in source for h in _GOVERNMENT_HINTS) or any(h in article.url.lower() for h in _GOVERNMENT_HINTS):
        return "공식발표(IR·정책)"
    return _CATEGORY_MATERIAL_TYPE.get(article.category, "기사")


def _credibility(article: SummarizedArticle) -> str:
    source = article.source_name.lower()
    url = article.url.lower()
    combined = f"{source} {url}"

    if article.category == "academic":
        if any(h in combined for h in _PREPRINT_HINTS):
            return "B (프리프린트, 동료심사 전)"
        if any(h in combined for h in _PEER_REVIEW_HINTS):
            return "A"
        return "B"

    if any(name in combined for name in _TIER1_NEWS | _TIER1_RESEARCH):
        return "A"
    if any(h in combined for h in _GOVERNMENT_HINTS):
        return "A"
    if any(h in combined for h in _PREPRINT_HINTS):
        return "B (프리프린트, 동료심사 전)"

    enterprise_ir = {"press release", "ir.", "investor", "newsroom", "보도자료"}
    if article.category == "enterprise" or any(h in combined for h in enterprise_ir):
        return "B"

    return "B"


def _credibility_grade(credibility: str) -> str:
    return credibility[0]


_C_SOURCE_HINTS = {
    "blogspot",
    "wordpress.com",
    "medium.com",
    "substack.com",
    "reddit.com",
    "twitter.com",
    "x.com",
    "t.co",
}


def log_to_summarized_article(log: dict) -> SummarizedArticle:
    """Reconstruct a SummarizedArticle from a stored daily log row."""
    published_at = None
    raw_published = log.get("published_at")
    if raw_published:
        try:
            published_at = datetime.fromisoformat(str(raw_published))
        except ValueError:
            published_at = None

    return SummarizedArticle(
        title=log["title"],
        url=log["url"],
        source_name=log.get("source_name", ""),
        category=log.get("category", "tech_news"),
        published_at=published_at,
        matched_keywords=list(log.get("matched_keywords") or []),
        llm_summary=log.get("llm_summary", ""),
        key_trends=list(log.get("key_trends") or []),
        ko_summary_steps=list(log.get("ko_summary_steps") or []),
        en_summary_steps=list(log.get("en_summary_steps") or []),
    )


def _is_c_grade_source(article: SummarizedArticle) -> bool:
    combined = f"{article.source_name} {article.url}".lower()
    return any(hint in combined for hint in _C_SOURCE_HINTS)


def monthly_credibility_grade(log: dict) -> str | None:
    """Return A or B for monthly reports; None if the source is C-grade."""
    report_grade = log.get("report_credibility")
    if report_grade:
        if report_grade == "C":
            return None
        if report_grade in ("A", "B"):
            return report_grade

    article = log_to_summarized_article(log)
    if _is_c_grade_source(article):
        return None

    grade = _credibility_grade(_credibility(article))
    if grade == "C":
        return None
    return grade if grade in ("A", "B") else "B"


def prepare_logs_for_monthly(logs: list[dict]) -> tuple[list[dict], int]:
    """Keep only A/B-grade logs and attach ``credibility_grade`` to each entry."""
    eligible: list[dict] = []
    excluded = 0

    for log in logs:
        grade = monthly_credibility_grade(log)
        if grade is None:
            excluded += 1
            continue
        eligible.append({**log, "credibility_grade": grade})

    return eligible, excluded


def monthly_credibility_distribution(logs: list[dict]) -> str:
    """Format monthly credibility counts using A/B only."""
    counts = Counter(log.get("credibility_grade", "B") for log in logs)
    return f"A {counts.get('A', 0)}건 / B {counts.get('B', 0)}건"


def _infer_tags(article: SummarizedArticle) -> list[str]:
    text = " ".join(
        [
            article.title,
            article.llm_summary,
            " ".join(article.key_trends),
            " ".join(article.matched_keywords),
            article.category,
        ]
    ).lower()

    tags: list[str] = []
    for pattern, tag in _TAG_RULES:
        if re.search(pattern, text, re.IGNORECASE) and tag not in tags:
            tags.append(tag)

    if article.category == "academic" and "#논문" not in tags:
        tags.insert(0, "#논문")
    if not tags:
        tags.append("#기술")
    return tags[:4]


def _strip_heading(text: str) -> str:
    """Remove bold headings and numbered-step prefixes from a summary line."""
    text = text.strip()
    # Remove **Bold:** style headings (English and Korean)
    text = re.sub(r"^\*\*[^*]+:\*\*\s*", "", text)
    # Remove "Step N - Label:" or "N단계 - 레이블:" style prefixes
    text = re.sub(r"^(?:Step\s+\d+\s*[-–]\s*\S.*?:|[\d]+단계\s*[-–]\s*\S.*?:)\s*", "", text, flags=re.IGNORECASE)
    return text


def _build_summary_lines(article: SummarizedArticle) -> list[str]:
    steps = article.ko_summary_steps or article.en_summary_steps
    facts: list[str] = []

    for step in steps:
        cleaned = polish_korean(strip_cjk_from_korean(_strip_heading(step)))
        cleaned = re.sub(r"\[\d+\]\s*$", "", cleaned).strip()
        if cleaned and not cleaned.startswith("(해석)"):
            facts.append(cleaned)
        if len(facts) >= 3:
            break

    if len(facts) < 2 and article.llm_summary:
        headline = re.sub(r"\s*Source:.*$", "", article.llm_summary, flags=re.IGNORECASE).strip()
        if headline and headline not in facts:
            facts.insert(0, headline)

    while len(facts) < 2:
        facts.append("원문 기준 핵심 사실을 추가 확인 필요")

    interpretation = ""
    if article.keyword_relevance:
        best = _best_from_relevance(article.keyword_relevance)
        if best:
            interpretation = best
    if not interpretation and article.key_trends:
        interpretation = f"{article.key_trends[0]} 흐름과 연결되는 시장 신호로 보임"

    if interpretation:
        facts.append(f"(해석) {interpretation}")

    return facts[:5]


def _time_label(article: SummarizedArticle, index: int) -> str:
    if article.published_at:
        return article.published_at.strftime("%H:%M")
    return f"{index:02d}"


def _published_date(article: SummarizedArticle, fallback: date) -> str:
    if article.published_at:
        return article.published_at.strftime("%Y-%m-%d")
    return fallback.isoformat()


def _first_sentence(text: str, hard_limit: int = 280) -> str:
    """Return the first complete sentence from *text*.

    Always extracts only the first sentence (up to the first . ! ?),
    even when the full text is shorter than *hard_limit*.
    Falls back to a word-boundary truncation if no sentence end is found.
    """
    text = text.strip()

    # Always try to extract the first sentence
    m = re.search(r"^(.+?[.!?])(?:\s|$)", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        if len(candidate) >= 10:
            if len(candidate) <= hard_limit:
                return candidate
            # Sentence itself is too long — truncate at word boundary
            last_space = candidate[:hard_limit].rfind(" ")
            if last_space > hard_limit * 0.6:
                return candidate[:last_space].rstrip(",.;:") + "…"
            return candidate[:hard_limit] + "…"

    # No sentence boundary found — return full text or truncate
    if len(text) <= hard_limit:
        return text
    last_space = text[:hard_limit].rfind(" ")
    if last_space > hard_limit * 0.6:
        return text[:last_space].rstrip(",.;:") + "…"
    return text[:hard_limit] + "…"


def _kw_score(text: str, keywords: list[str]) -> int:
    """Count how many of *keywords* appear in *text* (case-insensitive)."""
    t = text.lower()
    return sum(1 for k in keywords if k.lower() in t)


# Patterns that mark a sentence as too vague to display in the executive summary.
# Compiled patterns for sentence-final -다체 → -함/임체 normalization.
# Applied to the one-liner executive-summary bullets so the style is uniform.
_HAMCHE_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"해야\s*한다([.。]?)$"), r"해야 함\1"),
    (re.compile(r"([가-힣])한다([.。]?)$"), r"\1함\2"),
    (re.compile(r"([가-힣])이다([.。]?)$"), r"\1임\2"),
    (re.compile(r"([가-힣])있다([.。]?)$"), r"\1있음\2"),
    (re.compile(r"([가-힣])없다([.。]?)$"), r"\1없음\2"),
    (re.compile(r"([가-힣])된다([.。]?)$"), r"\1됨\2"),
    (re.compile(r"([가-힣])보인다([.。]?)$"), r"\1보임\2"),
    (re.compile(r"([가-힣])온다([.。]?)$"), r"\1옴\2"),
]


def _to_hamche(text: str) -> str:
    """Normalize sentence-final Korean -다체 endings to -함/임체 (명사형 종결).

    Applies only to the very end of the string so that mid-sentence
    clauses ending in -다 (e.g. relative clauses) are not affected.
    """
    for pattern, replacement in _HAMCHE_FIXES:
        text = pattern.sub(replacement, text)
    return text


_VAGUE_PATTERNS = re.compile(
    r"관련(이|성이|된)\s*(있음|높음|깊음|있다|높다)[.。]?$"
    r"|^이\s*기사는.{0,20}관련"
    r"|관련성이\s*높은\s*내용을\s*담고"
    r"|관련이\s*없는",
    re.IGNORECASE,
)


def _is_vague(sentence: str) -> bool:
    """Return True if *sentence* is a generic, uninformative placeholder."""
    s = sentence.strip()
    if len(s) < 45:
        return True
    if _VAGUE_PATTERNS.search(s):
        return True
    return False


def _best_from_relevance(keyword_relevance: str) -> str:
    """Return the first *specific* sentence from keyword_relevance text.

    Splits on sentence-ending punctuation and skips vague sentences.
    Returns empty string if nothing useful is found.
    """
    kr = polish_korean(strip_cjk_from_korean(keyword_relevance)).strip()
    kr = re.sub(r"\[\d+\]\s*$", "", kr).strip()
    if not kr:
        return ""

    # Split into individual sentences
    raw_sentences = re.split(r"(?<=[.!?])\s+", kr)
    for raw in raw_sentences:
        s = raw.strip().rstrip(".")
        if not s:
            continue
        candidate = s + ("." if not raw.endswith((".","!","?")) else "")
        if not _is_vague(candidate):
            return candidate
    return ""


def _one_liner(article: SummarizedArticle, top_keywords: list[str] | None = None) -> str:
    """Extract the single most keyword-relevant sentence for the executive summary.

    Priority:
      1. keyword_relevance field — scan all sentences for the first specific one.
         Vague / generic sentences are skipped entirely.
      2. Best-scoring ko_summary_step by top_keywords match count, then by
         preferred index order (3 → 0 → 1 → 2 → 4).
      3. llm_summary headline as last resort.
    """
    kws = top_keywords or []

    # 1. LLM-generated keyword_relevance: find the first specific sentence
    if article.keyword_relevance:
        best = _best_from_relevance(article.keyword_relevance)
        if best:
            return _to_hamche(_first_sentence(best))

    # 2. Pick the ko_summary_step most relevant to the tracked keywords
    steps = article.ko_summary_steps
    _pref = {3: 0, 0: 1, 1: 2, 2: 3, 4: 4}  # preferred index order

    candidates: list[tuple[int, int, int, str]] = []  # (neg_score, pref, idx, text)
    for idx, raw in enumerate(steps):
        cleaned = polish_korean(strip_cjk_from_korean(_strip_heading(raw)))
        cleaned = re.sub(r"\[\d+\]\s*$", "", cleaned).strip()
        if not cleaned or cleaned.startswith("(해석)") or len(cleaned) <= 15:
            continue
        score = _kw_score(cleaned, kws)
        candidates.append((-score, _pref.get(idx, 9), idx, cleaned))

    if candidates:
        candidates.sort()  # highest score first, then preferred index
        best = candidates[0][3]
        return _to_hamche(_first_sentence(best))

    # 3. llm_summary headline
    if article.llm_summary:
        h = re.sub(r"\s*Source:.*$", "", article.llm_summary, flags=re.IGNORECASE).strip()
        h = strip_cjk_from_korean(h)
        return _to_hamche(_first_sentence(h))
    return ""


def _build_executive_summary(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None = None,
) -> list[str]:
    """Build a concise executive summary covering every article at a glance.

    Structure:
      1. One-sentence synthesis (count + dominant theme).
      2. Bullet per article — title + key insight in one line.
      3. Notable signal + contradiction note.
    """
    # Top 3 most representative themes (first trend per article, deduplicated, capped)
    top_themes = list(dict.fromkeys(t for a in articles for t in a.key_trends[:1]))[:3]
    themes_str = ", ".join(top_themes) if top_themes else "기술·시장 동향"

    sources = ", ".join(dict.fromkeys(a.source_name for a in articles[:3]))
    extra = f" 외 {len(articles) - 3}개 출처" if len(articles) > 3 else ""

    synthesis = (
        f"오늘 수집된 {len(articles)}건 ({sources}{extra}) — "
        f"핵심 흐름: **{themes_str}**. 아래 항목별 1줄 요약으로 전체 내용을 파악할 것."
    )

    lines = [
        "## 오늘의 요약 (Daily Executive Summary)",
        "",
        synthesis,
        "",
        "**항목별 핵심 요약:**",
    ]

    for article in articles:
        one = _one_liner(article, top_keywords)
        short_title = article.title[:55] + ("…" if len(article.title) > 55 else "")
        if one:
            lines.append(f"- **{short_title}**: {one}")
        else:
            lines.append(f"- **{short_title}**")

    all_trends = list(dict.fromkeys(t for a in articles for t in a.key_trends[:2]))[:4]
    signal = ", ".join(all_trends) if all_trends else themes_str

    lines += [
        "",
        f"- **눈여겨볼 신호:** {signal}",
        "- **상충되는 정보:** (해당 없음)",
        "",
        "---",
        "",
    ]
    return lines


def _build_item_block(
    article: SummarizedArticle,
    index: int,
    log_date: date,
    top_keywords: list[str] | None,
) -> list[str]:
    material = _material_type(article)
    credibility = _credibility(article)
    tags = _infer_tags(article)
    summary_lines = _build_summary_lines(article)

    note_parts: list[str] = []
    if top_keywords:
        note_parts.append(f"분석 키워드: {', '.join(top_keywords[:3])}")
    if article.matched_keywords:
        note_parts.append(f"매칭: {', '.join(article.matched_keywords[:3])}")
    note = " · ".join(note_parts) if note_parts else ""

    lines = [
        f"### {_time_label(article, index)} {article.title}",
        "",
        f"- **자료유형:** {material}",
        f"- **출처:** {article.source_name}",
        f"- **저자/발행기관:** {article.source_name}",
        f"- **발행일:** {_published_date(article, log_date)}",
        f"- **링크/DOI:** {article.url}",
    ]

    # English original — shown first so readers can compare
    en_steps = article.en_summary_steps or []
    if en_steps:
        lines.append("- **요약 (영문 원문):**")
        for en_step in en_steps[:3]:
            en_clean = _strip_heading(en_step)
            en_clean = re.sub(r"\[\d+\]\s*$", "", en_clean).strip()
            if en_clean:
                lines.append(f"  - {en_clean}")

    # Korean translation
    lines.append("- **요약 (한국어 번역):**")
    for line in summary_lines:
        lines.append(f"  - {line}")

    lines += [
        f"- **신뢰도:** {credibility}",
        f"- **태그:** {' '.join(tags)}",
    ]
    if note:
        lines.append(f"- **비고:** {note}")
    lines.append("")
    return lines


def _build_markdown(
    log_date: date,
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None,
    recorder: str | None,
) -> str:
    paper_count = sum(1 for a in articles if _material_type(a) == "논문")
    article_count = len(articles) - paper_count

    cred_counts = Counter(_credibility_grade(_credibility(a)) for a in articles)
    author = recorder or os.getenv("DAILY_LOG_RECORDER", "Tech Market Monitor (auto)")

    lines: list[str] = [
        "# 데일리 리서치 로그",
        "",
        f"날짜: {log_date.isoformat()}",
        f"기록자: {author}",
        f"총 항목 수: {len(articles)}건 (기사 {article_count} / 논문 {paper_count})",
        f"신뢰도 분포: A {cred_counts.get('A', 0)}건 / B {cred_counts.get('B', 0)}건 / C {cred_counts.get('C', 0)}건",
        "",
    ]

    if articles:
        lines += _build_executive_summary(articles, top_keywords)

    lines += ["## 항목 기록", ""]

    for index, article in enumerate(articles, start=1):
        lines += _build_item_block(article, index, log_date, top_keywords)

    lines += [
        "---",
        "",
        "## 태그 분류체계 (월간 보고서 챕터와 매칭)",
        "",
        "| 태그 | 의미 |",
        "|------|------|",
        "| #기술 | 신기술, R&D, 기술 발표 |",
        "| #논문 | 학술 연구 결과 (성능, 실험, 방법론) |",
        "| #투자 | 투자 라운드, 밸류에이션, 펀딩 |",
        "| #M&A | 인수합병, 전략적 제휴 |",
        "| #제품출시 | 신제품, 서비스 런칭 |",
        "| #기업동향 | 조직, 인력, 실적, 전략 |",
        "| #규제 | 법안, 정책, 표준 |",
        "| #경쟁 | 경쟁사 비교, 점유율, 포지셔닝 |",
        "| #시장수치 | 시장규모/성장률 추정치 |",
        "| #리스크 | 사고, 논란, 부정적 전망 |",
        "| #전문가전망 | 애널리스트/전문가 예측 |",
        "",
        "## 신뢰도 등급 기준",
        "",
        "- **A (높음):** 피어리뷰 학술지 논문, 1차 보도(공식발표 인용), Tier-1 통신사(Reuters/Bloomberg/AP), 정부·국제기구 통계, Tier-1 시장조사기관(Gartner/IDC/McKinsey)",
        "- **B (중간):** 프리프린트(arXiv 등 동료심사 전), 업계 전문매체, 2차 인용 보도, 기업 자체 발표(IR/보도자료)",
        "- **C (참고):** 익명 소스, 추측성 기사, 단순 재가공 콘텐츠, 미검증 블로그",
        "",
    ]

    return "\n".join(lines)
