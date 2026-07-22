from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from src.models import SummarizedArticle
from src.policy_priority import gov_target_pass_label, gov_target_score, is_gov_target
from src.rd_targeting import (
    build_rd_targeting_block,
    compute_rd_match_score,
    format_rd_link_point,
    investment_signal_score,
    parse_rd_fields,
)
from src.summarizer import (
    normalize_korean_endings,
    normalize_korean_endings_sentences,
    polish_korean,
    repolish_summarized_article,
    strip_cjk_from_korean,
)

logger = logging.getLogger(__name__)

_OUTPUT_BASE = Path(__file__).resolve().parent.parent / "output" / "daily"
_MONITORING_KEYWORD_HEADER_LIMIT = 5


def format_monitoring_keyword_header(
    keywords: list[str] | None,
    *,
    mark: bool = True,
) -> str:
    """Report header label: first 5 keywords ·-joined, with 등 when more remain."""
    kws = [kw for kw in (keywords or []) if (kw or "").strip()]
    if not kws:
        return "(미설정)"
    shown = kws[:_MONITORING_KEYWORD_HEADER_LIMIT]
    if mark:
        body = " · ".join(f"<mark>{kw}</mark>" for kw in shown)
    else:
        body = " · ".join(shown)
    if len(kws) > len(shown):
        return f"{body} 등"
    return body

_TIER1_NEWS = {"연합뉴스", "yna", "뉴시스", "newsis"}
_TIER1_RESEARCH = {
    "kistep",
    "kiet",
    "iitp",
    "kipo",
    "ketep",
    "keit",
    "kiat",
    "tipa",
    "nrf",
    "kaia",
    "krit",
    "kepco",
    "koita",
    "kisdi",
    "pacst",
}
_PEER_REVIEW_HINTS = {"kci", "dbpia", "ieee", "springer", "elsevier", "wiley", "nature", "science", "kisti", "etri"}
_PREPRINT_HINTS = {"arxiv", "biorxiv", "medrxiv", "ssrn", "preprint", "프리프린트"}
_GOVERNMENT_HINTS = {
    "motie",
    "motir",
    "msit",
    "mss",
    "mw",
    "moe",
    "molit",
    "mcee",
    "mofe",
    "moef",
    "mnd",
    "kasa",
    "과기정통",
    "산업통상",
    "중소벤처",
    "보건복지",
    "국토교통",
    "기후에너지",
    "재정경제",
    "우주항공",
    "국방부",
    "kipo",
    "ketep",
    "keit",
    "kiat",
    "tipa",
    "kaia",
    "krit",
    "nrf",
    "pacst",
    ".go.kr",
}
_KOREAN_MAJOR_MEDIA = {
    "헤럴드",
    "herald",
    "동아",
    "donga",
    "경향",
    "khan",
    "한겨레",
    "hani",
    "파이낸셜",
    "fnnews",
    "전자신문",
    "etnews",
    "zdnet",
    "한국경제",
    "hankyung",
    "매일경제",
    "mk.co.kr",
    "전기신문",
    "electimes",
    "에너지경제",
    "ekn.kr",
    "에너지타임즈",
    "energytimes",
    "인더스트리뉴스",
    "industrynews",
}

CREDIBILITY_LEGEND_A = (
    "정부·공공기관 원문(부처·전담기관 .go.kr/.re.kr/.or.kr 보도자료), "
    "연합뉴스·뉴시스 1차 보도, "
    "공공 R&D·정책기관(KISTEP·KIET·KIPO·KETEP·KEIT·한국전력 등), "
    "국내 학술지·국책연구원 동료심사 논문"
)
CREDIBILITY_LEGEND_B = (
    "국내 경제·IT·에너지 전문매체(헤럴드경제·동아일보·매일경제·전자신문·"
    "전기신문·에너지경제신문·에너지타임즈·인더스트리뉴스·ZDNet Korea 등), "
    "2차 인용·전문자료 요약, 기업·공기업 IR/보도자료"
)
CREDIBILITY_LEGEND_C = (
    "익명 소스, 추측성 기사, 단순 재가공 콘텐츠, 미검증 블로그 — "
    "**자동 생성 시에는 C가 나오지 않음. 수동 기록 시에만 사용**"
)


def credibility_legend_lines() -> list[str]:
    """Footer legend for daily markdown (Korea-only source scope)."""
    return [
        "## 신뢰도 등급 기준",
        "",
        f"- **A (높음):** {CREDIBILITY_LEGEND_A}",
        f"- **B (중간):** {CREDIBILITY_LEGEND_B}",
        f"- **C (참고):** {CREDIBILITY_LEGEND_C}",
        "",
    ]

_TAG_RULES: list[tuple[str, str]] = [
    (r"invest|fund|series|valuation|펀딩|투자|유치", "#투자"),
    (r"acqui|merger|m&a|합병|인수|제휴", "#M&A"),
    (r"launch|release|출시|런칭|unveil", "#제품출시"),
    (r"regulat|policy|법안|규제|standard|표준|compliance|기본\s*계획|행동\s*계획", "#규제"),
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

# Unique marker written only by save_empty_daily_report (not by low-relevance days).
_EMPTY_REPORT_MARKER = "<!-- tmm:empty-daily -->"


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

    iso = log_date.isoformat()
    report_path = out_dir / f"daily_{iso}.md"
    report_path.write_text(
        _build_markdown(log_date, articles, top_keywords, recorder),
        encoding="utf-8",
    )
    logger.info("Daily research log saved → %s", report_path)
    return report_path


def save_empty_daily_report(
    log_date: date,
    output_dir: Path | None = None,
    top_keywords: list[str] | None = None,
    recorder: str | None = None,
) -> Path:
    """Write a placeholder daily log when the pipeline found no articles."""
    out_dir = output_dir or _OUTPUT_BASE
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"daily_{log_date.isoformat()}.md"
    body = _build_markdown(log_date, [], top_keywords, recorder)
    report_path.write_text(
        f"{_EMPTY_REPORT_MARKER}\n{body}",
        encoding="utf-8",
    )
    logger.info("Empty daily research log saved → %s", report_path)
    return report_path


def is_empty_daily_report(log_date: date, output_dir: Path | None = None) -> bool:
    """True when the markdown is an intentional empty-day placeholder."""
    path = (output_dir or _OUTPUT_BASE) / f"daily_{log_date.isoformat()}.md"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return _EMPTY_REPORT_MARKER in text


def format_source_display_name(source_name: str) -> str:
    """Show ministry press releases as 보도자료, not legacy 정책브리핑 labels."""
    name = (source_name or "").strip()
    if not name:
        return name
    prefix = "정책브리핑 "
    if name.startswith(prefix):
        org = name[len(prefix) :].strip()
        if org:
            return org if org.endswith("보도자료") else f"{org} 보도자료"
    return name


def _material_type(article: SummarizedArticle) -> str:
    if article.category == "academic":
        return "논문"
    source = format_source_display_name(article.source_name).lower()
    url = article.url.lower()
    # Press-release boards / gov sources before Tier-1 research so
    # "KIPO 보도자료" etc. are not mislabeled as 보고서(시장조사).
    if (
        "보도자료" in source
        or any(h in source for h in _GOVERNMENT_HINTS)
        or any(h in url for h in _GOVERNMENT_HINTS)
    ):
        return "보도자료"
    if any(h in source for h in _TIER1_RESEARCH):
        return "보고서(시장조사)"
    return _CATEGORY_MATERIAL_TYPE.get(article.category, "기사")


def _homepage_bucket(material: str) -> str:
    """Map item-level 자료유형 to homepage count buckets."""
    if material == "논문":
        return "논문"
    if material in ("보도자료", "공식발표(IR·정책)"):
        return "보도자료"
    return "기사"


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

    if any(h in combined for h in _GOVERNMENT_HINTS):
        return "A"
    if any(name in combined for name in _TIER1_NEWS | _TIER1_RESEARCH):
        return "A"
    if any(h in combined for h in _PREPRINT_HINTS):
        return "B (프리프린트, 동료심사 전)"

    enterprise_ir = {"press release", "ir.", "investor", "newsroom", "보도자료"}
    if article.category == "enterprise" or any(h in combined for h in enterprise_ir):
        return "B"

    if any(hint in combined for hint in _KOREAN_MAJOR_MEDIA):
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

    return repolish_summarized_article(
        SummarizedArticle(
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
            keyword_relevance=str(log.get("keyword_relevance") or ""),
            ko_one_liner=str(log.get("ko_one_liner") or ""),
            rd_match_score=int(log.get("rd_match_score") or 0),
            rd_proposable_area=str(log.get("rd_proposable_area") or ""),
            rd_fact_basis=str(log.get("rd_fact_basis") or ""),
            rd_evidence_quotes=list(log.get("rd_evidence_quotes") or []),
        )
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
    if is_gov_target(article):
        tags.append("#정부계획")
        if not any(t == "#협력" for t in tags):
            tags.append("#협력")
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


_MARK_TAG_RE = re.compile(r"</?mark>", re.IGNORECASE)
_PROTECTED_SPAN_RE = re.compile(
    r"\[[^\]]*\]\([^)]+\)|<mark>.*?</mark>|https?://\S+",
    re.IGNORECASE | re.DOTALL,
)


def strip_keyword_marks(text: str) -> str:
    """Remove <mark> wrappers (e.g. when re-parsing daily markdown)."""
    return _MARK_TAG_RE.sub("", text)


def _keywords_for_highlight(
    article: SummarizedArticle,
    top_keywords: list[str] | None = None,
) -> list[str]:
    """Matched + analysis keywords, longest-first; skip meta pass labels."""
    skip = {gov_target_pass_label().lower()}
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in list(article.matched_keywords or []) + list(top_keywords or []):
        kw = (raw or "").strip()
        if not kw or kw.lower() in skip:
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(kw)
    ordered.sort(key=len, reverse=True)
    return ordered


def _span_overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(not (end <= s or start >= e) for s, e in spans)


def _highlight_keywords(text: str, keywords: list[str]) -> str:
    """Wrap keyword occurrences in <mark>…</mark> (case-insensitive)."""
    if not text or not keywords:
        return text

    ordered = sorted(
        {kw.strip() for kw in keywords if kw and kw.strip()},
        key=len,
        reverse=True,
    )
    if not ordered:
        return text

    protected = [(m.start(), m.end()) for m in _PROTECTED_SPAN_RE.finditer(text)]
    lower = text.lower()
    hits: list[tuple[int, int]] = []

    for kw in ordered:
        needle = kw.lower()
        start = 0
        while True:
            idx = lower.find(needle, start)
            if idx < 0:
                break
            end = idx + len(kw)
            if not _span_overlaps(idx, end, protected) and not _span_overlaps(
                idx, end, hits
            ):
                hits.append((idx, end))
            start = idx + 1

    if not hits:
        return text

    hits.sort(key=lambda span: span[0], reverse=True)
    result = text
    for start, end in hits:
        result = f"{result[:start]}<mark>{result[start:end]}</mark>{result[end:]}"
    return result


def _highlight_after_md_label(line: str, keywords: list[str]) -> str:
    """Highlight only the value after a `- **Label:**` markdown field."""
    match = re.match(r"^(.*?:\*\*\s*)(.*)$", line)
    if match:
        return match.group(1) + _highlight_keywords(match.group(2), keywords)
    return _highlight_keywords(line, keywords)


def _build_summary_lines(
    article: SummarizedArticle,
    top_keywords: list[str] | None = None,
) -> list[str]:
    steps = article.ko_summary_steps
    facts: list[str] = []

    rd_heading_prefixes = ("투자 주체", "투자 목적", "위탁 연구 니즈", "접근 전략")
    for step in steps:
        cleaned = polish_korean(strip_cjk_from_korean(_strip_heading(step)))
        cleaned = re.sub(r"\[\d+\]\s*$", "", cleaned).strip()
        cleaned = normalize_korean_endings_sentences(cleaned)
        if cleaned and not cleaned.startswith("(해석)"):
            if any(label in step for label in rd_heading_prefixes):
                continue
            facts.append(cleaned)
        if len(facts) >= 3:
            break

    if len(facts) < 2 and article.llm_summary:
        headline = re.sub(r"\s*(?:Source|출처):.*$", "", article.llm_summary, flags=re.IGNORECASE).strip()
        if headline and headline not in facts:
            facts.insert(0, headline)

    while len(facts) < 2:
        facts.append("원문 기준 핵심 사실을 추가 확인 필요")

    interpretation = ""
    if article.keyword_relevance and _keyword_relevance_is_valid(
        article, article.keyword_relevance
    ):
        best = _best_from_relevance(article.keyword_relevance)
        level = _classify_relevance(article, top_keywords or [])
        if best and _relevance_trustworthy(article, best, level, top_keywords or []):
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


def _item_heading_text(article: SummarizedArticle, index: int) -> str:
    title = article.title.replace("…", "").replace("...", "").strip()
    return f"{_time_label(article, index)} {title}"


def _github_heading_slug(text: str, used: set[str]) -> str:
    """Match GitHub heading anchor slugs so summary links work on github.com."""
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    base = slug or "section"
    candidate = base
    n = 1
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    used.add(candidate)
    return candidate


def _build_item_slugs(articles: list[SummarizedArticle]) -> dict[str, str]:
    used: set[str] = set()
    slugs: dict[str, str] = {}
    for index, article in enumerate(articles, start=1):
        slugs[article.url] = _github_heading_slug(_item_heading_text(article, index), used)
    return slugs


def _item_anchor_tag(slug: str) -> str:
    return f'<a id="{slug}"></a>'


def _item_heading_md(article: SummarizedArticle, index: int) -> str:
    return f"### {_item_heading_text(article, index)}"


def _truncate_text(text: str, hard_limit: int) -> str:
    """Truncate at word boundary without ellipsis."""
    text = text.strip()
    if len(text) <= hard_limit:
        return text
    last_space = text[:hard_limit].rfind(" ")
    if last_space > hard_limit * 0.6:
        return text[:last_space].rstrip(",.;:")
    return text[:hard_limit].rstrip(",.;:")


_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def _md_link(label: str, url: str) -> str:
    """Markdown hyperlink safe for daily tables and item fields."""
    safe_label = (
        (label or "원문")
        .replace("[", "［")
        .replace("]", "］")
        .replace("|", "\\|")
        .strip()
        or "원문"
    )
    return f"[{safe_label}]({url.strip()})"


def _strip_md_links(text: str) -> str:
    """Remove markdown link wrappers, keeping the label text."""
    return _MD_LINK_RE.sub(r"\1", text)


def _article_url(article: SummarizedArticle) -> str:
    return (article.url or "").strip()


def _is_http_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def _link_text(text: str, url: str) -> str:
    """Wrap *text* in a markdown link when *url* is http(s)."""
    if _is_http_url(url):
        return _md_link(text, url)
    return text


def _item_summary_link(
    article: SummarizedArticle,
    slug: str,
    max_len: int = 45,
    highlight_keywords: list[str] | None = None,
) -> str:
    title = article.title.replace("…", "").replace("...", "").strip()
    short = _truncate_text(title, max_len)
    if highlight_keywords:
        short = _highlight_keywords(short, highlight_keywords)
    url = _article_url(article)
    if _is_http_url(url):
        return _md_link(short, url)
    return f"[{short}](#{slug})"


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
            return _truncate_text(candidate, hard_limit)

    if len(text) <= hard_limit:
        return text
    return _truncate_text(text, hard_limit)


def _kw_score(text: str, keywords: list[str]) -> int:
    """Count how many of *keywords* appear in *text* (case-insensitive)."""
    t = text.lower()
    return sum(1 for k in keywords if k.lower() in t)


_POWER_DIRECT_MATCHES = frozenset(
    {
        "power system",
        "power grid",
        "smart grid",
        "microgrid",
        "grid",
        "전력계통",
        "스마트그리드",
        "파워그리드",
        "전력망",
        "마이크로그리드",
        "송배전",
        "계통안정",
        "전력품질",
        "수요반응",
        "가상발전소",
        "vpp",
    }
)
_POWER_INDIRECT_MATCHES = frozenset(
    {
        "data center",
        "bess",
        "battery energy storage",
        "renewable energy",
        "energy storage",
        "renewable",
        "에너지저장",
        "에너지 저장",
        "재생에너지",
        "신재생",
        "에너지전환",
    }
)
_TANGENTIAL_MATCHES = frozenset({"ai infrastructure", "supply chain", "투자", "예산", "공모", "mou", "연구개발", "r&d"})

_NON_POWER_TITLE = re.compile(
    r"(?:"
    r"video|happyhorse|sora|seedance|claude|fable|mythos|fugu|sakana|"
    r"agent\s+orchestr|llm\s+agent|multi-model|multi-agent|layoff|"
    r"ai\s+video|video\s+model|video\s+gener"
    r")",
    re.IGNORECASE,
)
_POWER_SUPPLY_HINT = re.compile(
    r"ppa|power\s*purchase|전력\s*구매|가스\s*발전|natural\s*gas\s*power|"
    r"grid\s*capacity|전력망|송배전|transmission|distribution\s*grid",
    re.IGNORECASE,
)
_POWER_TEXT_HINT = re.compile(
    r"전력계통|파워그리드|스마트그리드|전력망|power\s*system|power\s*grid|"
    r"smart\s*grid|microgrid|grid\s*stability|계통",
    re.IGNORECASE,
)
_RELEVANCE_ORDER = {"direct": 0, "indirect": 1, "weak": 2, "none": 3}
_RELEVANCE_LABEL = {"direct": "직접", "indirect": "간접", "weak": "약함"}


def _relevance_sort_key(
    article: SummarizedArticle,
    top_keywords: list[str],
) -> tuple[int, str]:
    level = _classify_relevance(article, top_keywords)
    return _RELEVANCE_ORDER[level], article.title.lower()


def _sort_articles_by_relevance(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None,
) -> list[SummarizedArticle]:
    """Direct keyword relevance first, then indirect, weak, and none."""
    kws = top_keywords or []
    return sorted(articles, key=lambda a: _relevance_sort_key(a, kws))


def _title_anchor_tokens(title: str) -> list[str]:
    """Return distinctive tokens from a title for relevance validation."""
    stop = {
        "the", "and", "for", "with", "from", "plan", "plans", "new", "one",
        "largest", "over", "into", "that", "this", "their", "about", "beyond",
        "problem", "achieves", "capture", "rises", "sell", "called", "model",
    }
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'\+.-]{2,}", title)
    return [t for t in tokens if t.lower() not in stop and len(t) >= 4][:8]


def _keyword_relevance_is_valid(article: SummarizedArticle, text: str) -> bool:
    """Reject boilerplate or article-mismatched keyword_relevance text."""
    if not text or _is_vague(text):
        return False
    if _NON_POWER_TITLE.search(article.title) and _POWER_TEXT_HINT.search(text):
        return False
    anchors = _title_anchor_tokens(article.title)
    if not anchors:
        return True
    lower = text.lower()
    if not any(a.lower() in lower for a in anchors):
        return False
    if "snec 2026" in lower and "snec" not in article.title.lower():
        return False
    return True


def _article_text_blob(article: SummarizedArticle) -> str:
    """LLM-derived text used for display helpers — not for upgrading relevance alone."""
    kr = (
        article.keyword_relevance
        if _keyword_relevance_is_valid(article, article.keyword_relevance)
        else ""
    )
    return " ".join(
        [
            article.title,
            " ".join(article.ko_summary_steps[:3]),
            kr,
        ]
    )


def _source_relevance_blob(article: SummarizedArticle) -> str:
    """Title + matched keywords only — avoids LLM-invented grid linkage."""
    return " ".join([article.title, " ".join(article.matched_keywords)])


def _text_mentions_power(text: str, top_keywords: list[str]) -> bool:
    if _POWER_TEXT_HINT.search(text):
        return True
    return _kw_score(text, top_keywords) > 0


def _classify_relevance(article: SummarizedArticle, top_keywords: list[str]) -> str:
    """Classify how strongly an article relates to the monitoring keywords.

    Uses title + matched_keywords for direct/indirect decisions so speculative
    LLM mentions of 스마트그리드/전력계통 cannot inflate relevance.
    """
    matched = {k.lower() for k in article.matched_keywords}
    source = _source_relevance_blob(article)
    non_power_topic = bool(_NON_POWER_TITLE.search(article.title))

    if non_power_topic:
        if matched & _POWER_DIRECT_MATCHES:
            return "direct"
        if matched & (_POWER_INDIRECT_MATCHES | _TANGENTIAL_MATCHES):
            return "weak"
        return "none"

    if matched & _POWER_DIRECT_MATCHES:
        return "direct"
    if _text_mentions_power(source, top_keywords):
        return "direct"
    if _POWER_SUPPLY_HINT.search(source):
        return "direct"
    if matched & _POWER_INDIRECT_MATCHES:
        return "indirect"
    if matched & _TANGENTIAL_MATCHES:
        if _text_mentions_power(source, top_keywords):
            return "indirect"
        return "weak"
    if _text_mentions_power(source, top_keywords):
        return "indirect"
    return "none"


def _indirect_reason(article: SummarizedArticle) -> str:
    matched = {k.lower() for k in article.matched_keywords}
    blob = _article_text_blob(article)
    if _POWER_SUPPLY_HINT.search(blob):
        return "전력 공급·PPA"
    if "data center" in matched:
        return "데이터센터 전력 부하"
    if "bess" in matched or "battery energy storage" in matched:
        return "ESS·그리드 저장"
    if "supply chain" in matched:
        return "계통·스마트그리드용 반도체 공급"
    if "ai infrastructure" in matched:
        return "AI 인프라 전력 소비"
    return "전력 수요·공급 파급"


def _keyword_focus_phrase(top_keywords: list[str]) -> str:
    parts: list[str] = []
    for kw in top_keywords:
        if kw == "전력계통":
            parts.append("전력망 안정·용량·부하")
        elif kw == "파워그리드":
            parts.append("송전·배전·피크·VPP")
        elif kw == "스마트그리드":
            parts.append("지능형 운영·분산자원·수요반응")
        elif kw == "에너지고속도로":
            parts.append("장거리 송전·에너지 고속도로")
        elif "HVDC" in kw or "전력변환" in kw:
            parts.append("HVDC·전력변환·계통연계")
        elif "ESS" in kw or "계통연계" in kw:
            parts.append("장주기 ESS·계통연계")
        elif "그리드포밍" in kw or "Grid-forming" in kw:
            parts.append("그리드포밍 인버터")
        elif "DC Grid" in kw or kw == "DC Grid":
            parts.append("DC 그리드")
        elif "사이버보안" in kw:
            parts.append("전력망 사이버보안")
        elif "Digital Grid" in kw or "배전망" in kw:
            parts.append("배전망 디지털화")
        elif "출력예측" in kw:
            parts.append("재생에너지 출력예측")
        elif "유지관리" in kw:
            parts.append("송전설비 AI 유지관리")
        elif "AI 기반 전력계통" in kw:
            parts.append("AI 전력계통 운영")
    return ", ".join(parts[:3]) if parts else "전력·그리드"


def _keyword_connection(
    article: SummarizedArticle,
    top_keywords: list[str],
    level: str,
) -> str:
    """Last sentence in the executive-summary row: keyword relevance rationale."""
    kws = top_keywords
    kw_label = " · ".join(kws)

    if level == "direct":
        trigger = _relevance_trigger(article, "direct", top_keywords)
        hit = [kw for kw in kws if kw in _article_text_blob(article)]
        target = " · ".join(hit[:2]) if hit else kw_label
        focus = _keyword_focus_phrase(kws)
        return f"**[{target}]**와 직접 연관({trigger}, {focus} 주제와 일치)."

    if level == "indirect":
        reason = _indirect_reason(article)
        trigger = _relevance_trigger(article, "indirect", top_keywords)
        implication = _indirect_implication_plain(reason, top_keywords)
        return (
            f"**[{kw_label}]**와 간접 연관({trigger} 경로로 수집, 1차 주제는 전력망·스마트그리드가 아님. "
            f"{implication})."
        )

    return f"**[{kw_label}]**와 관련성 낮음."


def _relevance_trustworthy(
    article: SummarizedArticle,
    sentence: str,
    level: str,
    top_keywords: list[str],
) -> bool:
    if level == "direct":
        return True
    if _NON_POWER_TITLE.search(article.title):
        matched = {k.lower() for k in article.matched_keywords}
        if _text_mentions_power(sentence, top_keywords) and not (matched & _POWER_DIRECT_MATCHES):
            return False
    return True


_INTERPRETIVE_STEP_LABELS = (
    "투자 주체",
    "투자 목적",
    "위탁 연구 니즈",
    "접근 전략",
    "제안 R&D",
)
_INTERPRETIVE_SENTENCE_RE = re.compile(
    r"시장\s*신호"
    r"|연계\s*가능"
    r"|협력\s*가능"
    r"|정부의\s+.+와\s+연계"
    r"|로드맵\s*연계"
    r"|정책\s*정합"
    r"|접근\s*전략"
    r"|제안\s*R&D"
    r"|위탁\s*연구"
    r"|것으로\s*보임"
    r"|시사함|시사점"
    r"|흐름과\s*연결"
    r"|주목할\s*만",
    re.IGNORECASE,
)


def _step_is_fact_source(raw: str) -> bool:
    """True when a ko_summary_steps line is an overview fact, not R&D interpretation."""
    return not any(label in raw for label in _INTERPRETIVE_STEP_LABELS)


def _is_interpretive_sentence(sentence: str) -> bool:
    """True when the sentence is analysis/proposal rather than a source fact."""
    return bool(_INTERPRETIVE_SENTENCE_RE.search(sentence.strip()))


def _extract_fact_sentence(
    article: SummarizedArticle,
    top_keywords: list[str],
    level: str,
) -> str:
    """Pick the best one-sentence fact for the executive summary.

    Prefers LLM-generated ko_one_liner (5W1H-dense), then ko_summary_steps
    ranked by informativeness. Sentences must name their subject explicitly.
    Interpretive R&D fields and analyst commentary are excluded.
    """
    if article.ko_one_liner:
        one_liner = polish_korean(
            strip_cjk_from_korean(re.sub(r"\[\d+\]\s*$", "", article.ko_one_liner).strip())
        )
        if one_liner and not _is_vague(one_liner) and not _is_interpretive_sentence(one_liner):
            return one_liner

    anchors = _title_anchor_tokens(article.title)
    ranked: list[tuple[tuple, str]] = []

    for idx, raw in enumerate(article.ko_summary_steps):
        if not _step_is_fact_source(raw):
            continue
        cleaned = polish_korean(strip_cjk_from_korean(_strip_heading(raw)))
        cleaned = re.sub(r"\[\d+\]\s*$", "", cleaned).strip()
        if not cleaned or cleaned.startswith("(해석)"):
            continue
        for sentence in _split_sentences(cleaned):
            if _is_interpretive_sentence(sentence):
                continue
            if _is_vague(sentence):
                continue
            anchor_hits = sum(1 for a in anchors if a.lower() in sentence.lower())
            info_score = _informative_score(sentence)
            quant_rich = info_score >= 5 and bool(_QUANT_RE.search(sentence))
            deictic_bad = not quant_rich and (
                _has_deictic_subject(sentence) or _has_deictic_reference(sentence)
            )
            sort_key = (
                deictic_bad,
                -info_score,
                -anchor_hits,
                -_kw_score(sentence, top_keywords),
                _STEP_PREF.get(idx, 9),
            )
            ranked.append((sort_key, sentence))

    ranked.sort(key=lambda x: x[0])
    for _, best in ranked:
        return polish_korean(best)

    if article.llm_summary:
        headline = re.sub(r"\s*(?:Source|출처):.*$", "", article.llm_summary, flags=re.IGNORECASE).strip()
        if headline and not _is_vague(_first_sentence(headline)):
            return polish_korean(_first_sentence(headline))
    return ""


def _exec_summary_item(
    article: SummarizedArticle,
    top_keywords: list[str],
) -> tuple[str, str, str] | None:
    """Return (fact, level_label, connection) or None if not relevant enough."""
    level = _classify_relevance(article, top_keywords)
    if level in ("none", "weak"):
        return None
    fact = _extract_fact_sentence(article, top_keywords, level)
    if not fact:
        return None
    return fact, _RELEVANCE_LABEL[level], _keyword_connection(article, top_keywords, level)


def _build_daily_theme(
    articles: list[SummarizedArticle],
    top_keywords: list[str],
) -> str:
    levels = [_classify_relevance(a, top_keywords) for a in articles]
    direct_n = levels.count("direct")
    indirect_n = levels.count("indirect")
    if direct_n >= 2 and indirect_n >= 1:
        return (
            "전력계통·송배전 직접 이슈와 데이터센터 전력 수요·공급이 동시에 부각되는 날"
        )
    if direct_n >= 1:
        return "전력계통·파워그리드와 직접 연결된 기술·정책 이슈가 핵심인 날"
    if indirect_n >= 2:
        return "AI·데이터센터 확장이 전력 수요·그리드 부하로 이어지는 간접 신호가 다수인 날"
    if levels.count("weak") >= 1:
        return "추적 키워드와 직접 연관은 제한적이나, 데이터센터·인프라 확장의 간접 파급이 관찰되는 날"
    return "기술·시장 동향"


# Patterns that mark a sentence as too vague to display in the executive summary.
# A sentence is vague when it states no concrete fact and merely asserts that
# something is "important", "rapidly developing", or "related to keywords".
_VAGUE_PATTERNS = re.compile(
    # Original patterns
    r"관련(이|성이|된)\s*(있음|높음|깊음|있다|높다)[.。]?$"
    r"|관련성이\s*높은\s*내용을\s*담고"
    r"|관련이\s*없는"
    r"|직접적인\s*연관성"
    # Sentences starting with "이 기사는/이 논문은" — leads with meta-commentary, not facts
    r"|^이\s*(기사|논문|연구|보고서)는"
    # "rapidly developing/growing" — states no specific fact
    r"|빠르게\s*(발전하고|성장하고|확산되고|변화하고|발전함|성장함)"
    # "emphasises importance" — no specific event or number
    r"|중요성을\s*(강조|보여|나타내|시사)"
    r"|(중요한|핵심적인)\s*역할을\s*(함|하고|합니다|한다)"
    # "expected to have big impact" — vague prediction, no numbers
    r"|큰\s*영향을\s*미칠\s*것으로\s*(예상|전망)"
    # Three target keywords listed together with generic verb — no article fact
    r"|(전력계통|파워그리드|스마트그리드).{0,40}(전력계통|파워그리드|스마트그리드).{0,40}(빠르게|급속|발전|성장)"
    # Sentence starts with a target keyword followed by a generic definition or benefit
    r"|^(전력계통|파워그리드|스마트그리드)(은|는|이|가)\s*.{0,80}(도움이\s*될\s*수\s*있|필요한|기반\s*기술|고급\s*기술|역할을\s*함)"
    # Generic "important move/development" without specifics
    r"|중요한\s*(움직임|변화|발전임|사안)"
    # "demand is expected to grow" — no article-specific trigger
    r"|수요가\s*증가할\s*것으로\s*(예상|전망)"
    # "worth paying attention" filler
    r"|주목할\s*(만한|필요가\s*있)"
    r"|눈여겨봐야"
    # Abstract reactions without specifics — poor market intel
    r"|의문을\s*불러일으"
    r"|논란을\s*일으"
    r"|회의적\s*반응"
    # Negative / weak relevance: "관련하여 파급력을 미치지 않지만", "직접 관련이 없는"
    r"|관련하여.{0,40}않"
    r"|파급력을\s*미치지\s*않"
    r"|직접.*관련.{0,20}없"
    r"|관련성이\s*낮"
    # Generic "important role" with no specific fact
    r"|중요한\s*역할을\s*(할|하는|한|해야|함)"
    # Keyword used as subject of a generic market/opportunity statement
    r"|^(전력계통|파워그리드|스마트그리드)(은|는)\s*.{0,50}(잠재력|기회|투자|역할|시장\s*(규모|성장))"
    # "X의 발전을 위한" — keyword as goal destination, not article-specific fact
    r"|(전력계통|파워그리드|스마트그리드)\s*의\s*발전을\s*위한"
    # "X는 Y하는 시스템으로/시스템임" — plain dictionary definition, not article fact
    r"|^(전력계통|파워그리드|스마트그리드)(은|는)\s*.{0,60}(시스템으로|시스템임|시스템이다|네트워크로|기술임|기술이다)"
    # "필요성을 강조" — same vague structure as 중요성을 강조
    r"|필요성을\s*(강조|보여|나타내|시사)"
    # "우려가 커지고 있다" — generic concern without article specifics
    r"|우려가\s*(커지고|증가하고)\s*(있다|있음)"
    # "관련하여 … 강조됨" — relevance wrapper masquerading as conclusion
    r"|(관련하여|관련한)\s*.{0,40}(강조됨|시사됨|제시됨)[.。]?$"
    # Deictic / pronoun subjects — reader cannot tell what is meant without prior context
    r"|^이러한\s"
    r"|^이(?:는|가)\s"
    r"|^이\s*(기술|솔루션|방식|접근|프레임워크|시스템|연구|논문|기사|프로젝트|메커니즘|벤치마크|개발|결과)(?:은|는|이|가|의|에)?\s"
    r"|^해당\s*(기술|솔루션|방법|프레임워크|접근|분야|시스템)(?:은|는|이|가|의|에)?\s"
    r"|^본\s*(연구|논문|기사|기술|솔루션|프레임워크)(?:은|는|이|가|의|에)?\s"
    r"|^새로운\s*(프레임워크|접근(?:법)?|방법|시스템|모델)(?:은|는|이|가|의|에)?\s"
    r"|^제안된\s*(프레임워크|시스템|방법|접근(?:법)?|모델)(?:은|는|이|가|의|에)?\s"
    r"|^이\s+\S+\s*의\s*잠재"
    r"|잠재적\s*시장\s*영향(?:은|이)\s*(?:크|상당)"
    r"|^구체적인\s*시장\s*규모"
    r"|,\s*이\s*(기술|솔루션|방식|접근|프레임워크)(?:에|은|는|이|가|의)?\s"
    r"|,\s*이는\s",
    re.IGNORECASE,
)

# Always vague regardless of numbers — abstract reactions, meta-commentary, keyword filler.
_ABSTRACT_VAGUE_RE = re.compile(
    r"관련(이|성이|된)\s*(있음|높음|깊음|있다|높다)[.。]?$"
    r"|관련성이\s*높은\s*내용을\s*담고"
    r"|^이\s*(기사|논문|연구|보고서)는"
    r"|빠르게\s*(발전하고|성장하고|확산되고|변화하고|발전함|성장함)"
    r"|중요성을\s*(강조|보여|나타내|시사)"
    r"|필요성을\s*(강조|보여|나타내|시사)"
    r"|의문을\s*불러일으"
    r"|논란을\s*일으"
    r"|주목할\s*(만한|필요가\s*있)"
    r"|눈여겨봐야"
    r"|관련하여.{0,40}않"
    r"|파급력을\s*미치지\s*않"
    r"|직접.*관련.{0,20}없"
    r"|관련성이\s*낮"
    r"|^(전력계통|파워그리드|스마트그리드)(은|는)\s*.{0,60}(시스템으로|시스템임|시스템이다|네트워크로|기술임|기술이다)",
    re.IGNORECASE,
)

# Standalone check for deictic subjects (used before length heuristics).
_DEICTIC_SUBJECT_RE = re.compile(
    r"^이(?:는|가)\s"
    r"|^이\s+(?:프레임워크|기술|솔루션|방법|접근|시스템|연구|논문|기사|프로젝트|메커니즘|벤치마크|개발|결과|접근법)(?:은|는|이|가|의|에)?\s"
    r"|^이러한\s"
    r"|^해당\s"
    r"|^본\s+(?:연구|논문|기사|기술|솔루션|프레임워크)\s"
    r"|^새로운\s+(?:프레임워크|접근(?:법)?|방법|시스템|모델)(?:은|는|이|가|의|에)?\s"
    r"|^제안된\s+(?:프레임워크|시스템|방법|접근(?:법)?|모델)(?:은|는|이|가|의|에)?\s",
    re.IGNORECASE,
)

# Mid-sentence deictic references — subject unclear without prior context.
_DEICTIC_REFERENCE_RE = re.compile(
    r"(?<![가-힣A-Za-z])이\s+(?:프레임워크|기술|솔루션|방법|접근|시스템|연구|논문|메커니즘|벤치마크|프로젝트)(?:의|은|는|이|가|에)?\s"
    r"|,\s*이는\s"
    r"|이러한\s+(?:기술|솔루션|프레임워크|방법|과제|솔루션|워크로드)"
    r"|해당\s+(?:기술|프레임워크|솔루션|방법|시스템)",
    re.IGNORECASE,
)


def _has_deictic_reference(sentence: str) -> bool:
    """True when the sentence refers to the subject via a deictic anywhere."""
    return bool(_DEICTIC_REFERENCE_RE.search(sentence.strip()))


_STEP_PREF = {1: 0, 3: 1, 0: 2, 2: 3, 4: 4}

# Patterns that boost informativeness for market-research one-liners (5W1H signals).
_QUANT_RE = re.compile(
    r"\$\s?\d|"
    r"\d[\d,.]*\s*(억|조|만|%)|"
    r"\d[\d,.]*\s*(GW|MW|kW|GWh|MWh|"
    r"billion|million|trillion)|"
    r"\d{4}\s*년|"
    r"\d+\s*명",
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(
    r"인도네시아|한국|일본|중국|미국|유럽|동남아|아시아|"
    r"Indonesia|Korea|Japan|China|US|Europe|Asia|"
    r"서울|도쿄|싱가포르|베트남|인도|호주|오스트레일리아",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"건설|투자|계약|파트너십|인수|출시|발표|승인|도입|"
    r"감원|수주|공급|설치|확대|개발|협력|제휴|"
    r"회의적|의구심|비판|우려|반대",
)


def _informative_score(sentence: str) -> int:
    """Score how many 5W1H-style facts a sentence packs (higher = better)."""
    score = 0
    if _QUANT_RE.search(sentence):
        score += 3
    if _LOCATION_RE.search(sentence):
        score += 2
    if re.search(r"[A-Za-z][A-Za-z0-9+-]{3,}", sentence):
        score += 2
    if _ACTION_RE.search(sentence):
        score += 1
    if len(sentence) >= 70:
        score += 1
    return score


def _has_deictic_subject(sentence: str) -> bool:
    """True when the sentence subject is a pronoun/deictic, not a named entity."""
    s = sentence.strip()
    if not _DEICTIC_SUBJECT_RE.search(s):
        return False
    # "제안된 Hierarchical Neural …" — proper name follows; keep.
    if re.search(r"[A-Za-z][A-Za-z0-9+-]{4,}", s[:70]):
        return False
    return True


def _min_informative_length(sentence: str) -> int:
    """Shorter named-entity sentences may still be informative."""
    if re.search(r"[A-Za-z][A-Za-z0-9+-]{4,}|\d{2,}", sentence):
        return 32
    if not _has_deictic_subject(sentence) and not _has_deictic_reference(sentence):
        return 38
    return 45


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out: list[str] = []
    for raw in parts:
        s = raw.strip()
        if not s:
            continue
        if not s.endswith((".", "!", "?")):
            s += "."
        out.append(s)
    return out


def _is_vague(sentence: str) -> bool:
    """Return True if *sentence* is a generic, uninformative placeholder.

    Quant-rich sentences (5W1H facts with numbers/dates) stay even when they
    open with '이 프로젝트' etc. Abstract filler ('의문을 불러일으') is always vague.
    """
    s = sentence.strip()
    info = _informative_score(s)
    quant_rich = info >= 5 and bool(_QUANT_RE.search(s))

    if _ABSTRACT_VAGUE_RE.search(s):
        return True

    if quant_rich:
        return False

    if _has_deictic_subject(s) or _has_deictic_reference(s):
        return True
    if _VAGUE_PATTERNS.search(s):
        return True
    if len(s) < _min_informative_length(s):
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
            return normalize_korean_endings(candidate)
    return ""


def _one_liner(article: SummarizedArticle, top_keywords: list[str] | None = None) -> str:
    """Extract the single most keyword-relevant sentence for the executive summary."""
    kws = top_keywords or []
    item = _exec_summary_item(article, kws)
    if not item:
        return ""
    fact, _, connection = item
    return f"{fact} {connection}"


_MATCH_LABEL_KO: dict[str, str] = {
    "data center": "데이터센터(data center)",
    "bess": "BESS(배터리 저장)",
    "battery energy storage": "BESS(배터리 저장)",
    "power grid": "전력망(power grid)",
    "power system": "전력계통(power system)",
    "smart grid": "스마트그리드(smart grid)",
    "microgrid": "마이크로그리드(microgrid)",
    "ai infrastructure": "AI 인프라(ai infrastructure)",
    "supply chain": "공급망(supply chain)",
    "renewable energy": "재생에너지(renewable energy)",
    "energy storage": "에너지 저장(energy storage)",
}


def _match_label(term: str) -> str:
    return _MATCH_LABEL_KO.get(term.lower(), term)


def _relevance_trigger(
    article: SummarizedArticle,
    level: str,
    top_keywords: list[str],
) -> str:
    """Explain which match or text cue drove the direct/indirect classification."""
    matched = {k.lower() for k in article.matched_keywords}
    blob = _article_text_blob(article)

    if level == "direct":
        direct_hits = sorted(matched & _POWER_DIRECT_MATCHES)
        if direct_hits:
            label = _match_label(direct_hits[0])
            suffix = f"·{_match_label(direct_hits[1])}" if len(direct_hits) > 1 else ""
            return f"수집·매칭 키워드 {label}{suffix}에 해당"
        if _POWER_SUPPLY_HINT.search(blob):
            return "전력 공급·송배전·PPA(장기 전력 구매)가 기사의 핵심 내용"
        power_kws = [kw for kw in top_keywords if kw.lower() in blob.lower()]
        if power_kws:
            return f"기사 본문에 '{power_kws[0]}'이(가) 직접 등장"
        if _POWER_TEXT_HINT.search(blob):
            return "기사 본문에서 전력계통·전력망·스마트그리드가 핵심 주제"
        return "추적 키워드와 기사 주제가 그대로 겹침"

    indirect_hits = sorted(matched & (_POWER_INDIRECT_MATCHES | _TANGENTIAL_MATCHES))
    if indirect_hits:
        return _match_label(indirect_hits[0])
    if _text_mentions_power(blob, top_keywords):
        return "간접 매칭 키워드 + 본문 전력·그리드 언급"
    return "간접 영향 경로"


def _kw_impact_narrative(top_keywords: list[str], reason: str) -> str:
    """One readable sentence linking each tracking keyword to the indirect reason."""
    kw_set = set(top_keywords)

    if reason == "데이터센터 전력 부하":
        labels: list[str] = []
        if "전력계통" in kw_set:
            labels.append("**전력계통**(발전·송전 용량·피크 부하)")
        if "파워그리드" in kw_set:
            labels.append("**파워그리드**(배전망·전력 장기 구매 PPA)")
        if "스마트그리드" in kw_set:
            labels.append("**스마트그리드**(부하 예측·수요반응·피크 분산)")
        if any("ESS" in kw for kw in kw_set):
            labels.append("**장주기 ESS**(피크 완화·계통연계)")
        if labels:
            joined = ", ".join(labels)
            return (
                f"다만 데이터센터는 24시간 대량 전기를 쓰는 설비라, "
                f"신규 건설·확장 소식은 {joined} "
                f"쪽 이슈로 이어질 수 있음"
            )
    elif reason == "ESS·그리드 저장":
        return (
            "배터리·ESS는 전력 저장·피크 완화와 연결되나, "
            "기사는 배터리 기술·출시·시장이 중심이라 전력망 운영 이슈는 2순위"
        )
    elif reason == "AI 인프라 전력 소비":
        kws = " · ".join(top_keywords)
        return f"AI 인프라 확장은 {kws} 관점의 전력 수요·공급·망 운영에 간접 영향을 줄 수 있음"

    kws = " · ".join(top_keywords)
    return f"{reason} 경로로 {kws} 추적 키워드에 간접 영향 가능"


def _direct_implication_plain(top_keywords: list[str]) -> str:
    parts: list[str] = []
    for kw in top_keywords:
        if kw == "전력계통":
            parts.append("전력망 안정·용량·부하")
        elif kw == "파워그리드":
            parts.append("송전·배전·피크·VPP")
        elif kw == "스마트그리드":
            parts.append("지능형 운영·분산자원·수요반응")
        elif "ESS" in kw:
            parts.append("장주기 ESS·계통연계")
        elif "HVDC" in kw or "전력변환" in kw:
            parts.append("HVDC·전력변환")
    focus = ", ".join(parts[:3]) if parts else "전력·그리드"
    return (
        f"즉 기사가 다루는 핵심이 {focus} 등 추적 키워드와 바로 맞닿아 "
        f"'직접' 연관으로 분류함"
    )


def _indirect_implication_plain(reason: str, top_keywords: list[str]) -> str:
    """Plain explanation for indirect keyword linkage."""
    return _kw_impact_narrative(top_keywords, reason)


def _short_item_label(article: SummarizedArticle, limit: int = 48) -> str:
    return _truncate_text(article.title.strip(), limit)


def _signal_kw_label(
    article: SummarizedArticle,
    level_label: str,
    top_keywords: list[str],
) -> str:
    """Pick the most relevant tracking-keyword subset for the signal header."""
    blob = _article_text_blob(article).lower()
    hits = [kw for kw in top_keywords if kw.lower() in blob]
    if hits:
        return " · ".join(hits[:3])
    if level_label == "직접":
        return top_keywords[0] if top_keywords else "(미설정)"
    return " · ".join(top_keywords[:3]) if top_keywords else "(미설정)"


def _build_keyword_signal_for_group(
    group_items: list[tuple[SummarizedArticle, str, str, str]],
    level_label: str,
    top_keywords: list[str],
) -> str:
    articles = [row[0] for row in group_items]
    kw_part = _signal_kw_label(articles[0], level_label, top_keywords)
    level_key = "direct" if level_label == "직접" else "indirect"
    trigger = _relevance_trigger(articles[0], level_key, top_keywords)

    if level_label == "직접":
        if len(articles) == 1:
            ref = _short_item_label(articles[0])
            body = (
                f"{trigger}. {_direct_implication_plain(top_keywords)} "
                f"(해당 기사: {ref})"
            )
        else:
            refs = ", ".join(_short_item_label(a) for a in articles[:2])
            extra = f" 외 {len(articles) - 2}건" if len(articles) > 2 else ""
            body = (
                f"{trigger}. {_direct_implication_plain(top_keywords)} "
                f"(해당 기사: {refs}{extra})"
            )
    else:
        reason = _indirect_reason(articles[0])
        implication = _indirect_implication_plain(reason, top_keywords)
        if len(articles) == 1:
            ref = _short_item_label(articles[0])
            body = (
                f"제목·본문에 '{trigger}'가 있어 수집됐으나, "
                f"내용은 전력망·스마트그리드가 1차 주제는 아님. {implication} "
                f"(해당 기사: {ref})"
            )
        else:
            body = (
                f"오늘 {len(articles)}건 모두 '{trigger}' 키워드로 수집됐으나, "
                f"내용은 전력망·스마트그리드가 1차 주제는 아님. "
                f"{implication}"
            )

    return f"- **[{kw_part}]** **{level_label}** — {body}"


def _build_keyword_signals(
    items: list[tuple[SummarizedArticle, str, str, str]],
    top_keywords: list[str],
) -> list[str]:
    """Build up to 3 keyword-perspective signals (classification rationale, not fact repeats)."""
    groups: dict[tuple[str, str], list[tuple[SummarizedArticle, str, str, str]]] = defaultdict(list)

    ordered = sorted(
        items,
        key=lambda row: 0 if row[2] == "직접" else 1 if row[2] == "간접" else 2,
    )
    for row in ordered:
        article, _fact, level_label, _connection = row
        if level_label not in ("직접", "간접"):
            continue
        if level_label == "직접":
            group_key = ("직접", article.url)
        else:
            group_key = ("간접", _indirect_reason(article))
        groups[group_key].append(row)

    sorted_keys = sorted(
        groups.keys(),
        key=lambda k: (0 if k[0] == "직접" else 1, k[1]),
    )

    signals: list[str] = []
    for key in sorted_keys[:3]:
        level_label = key[0]
        signals.append(
            _build_keyword_signal_for_group(groups[key], level_label, top_keywords)
        )
    return signals


def _build_executive_summary(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None = None,
    article_slugs: dict[str, str] | None = None,
) -> list[str]:
    """Build R&D intelligence executive summary (Fraunhofer Korea).

    The summary block is fact-only: no interpretive themes, analyst commentary,
    or Fraunhofer targeting bullets. Interpretation stays in per-item blocks.
    """
    kws = top_keywords or []
    kw_header = format_monitoring_keyword_header(kws)
    stats = _build_rd_daily_stats(articles, kws)

    sources = ", ".join(dict.fromkeys(a.source_name for a in articles[:3]))
    extra = f" 외 {len(articles) - 3}개 출처" if len(articles) > 3 else ""
    high_score = sum(1 for a in articles if compute_rd_match_score(a, kws) >= 4)

    lines = [
        "## 오늘의 R&D 인텔리전스 요약",
        "",
        f"**모니터링 키워드:** {kw_header}",
        "",
        f"**수집 현황:** {stats}",
        "",
        f"오늘 수집 {len(articles)}건 (R&D 적합 4점 이상 {high_score}건) · {sources}{extra}",
        "",
        "**R&D 기회 스캔 (팩트 기반):**",
        "",
        "| R&D적합 | 핵심 이슈 (팩트) | 고객 타겟 | R&D 연계 포인트 | 팩트 체크 |",
        "|---------|-----------------|----------|----------------|----------|",
    ]

    slugs = article_slugs or _build_item_slugs(articles)
    ranked = sorted(
        articles,
        key=lambda a: (
            -compute_rd_match_score(a, kws),
            -gov_target_score(a),
            -investment_signal_score(a),
            a.title.lower(),
        ),
    )

    included_count = 0
    for article in ranked:
        score = compute_rd_match_score(article, kws)
        if score < 2:
            continue
        fields = parse_rd_fields(article.ko_summary_steps)
        issue = _extract_fact_sentence(article, kws, "direct")
        if not issue:
            basis = (article.rd_fact_basis or "").strip()
            if basis and basis not in ("명시 없음", "") and not _is_interpretive_sentence(basis):
                issue = _first_sentence(basis, hard_limit=200)
        if not issue:
            issue = article.title
        issue = issue.replace("|", "\\|")
        target = (fields.get("investment_actor") or "명시 없음").replace("|", "\\|")
        link_point = format_rd_link_point(
            article.rd_proposable_area,
            fields.get("pain_point", ""),
            fields.get("investment_purpose", ""),
        ).replace("|", "\\|")
        slug = slugs[article.url]
        hl_kws = _keywords_for_highlight(article, kws)
        link = _item_summary_link(article, slug, max_len=30, highlight_keywords=hl_kws)
        issue = _highlight_keywords(issue, hl_kws)
        target = _highlight_keywords(target, hl_kws)
        link_point = _highlight_keywords(link_point, hl_kws)
        url = _article_url(article)
        basis = (article.rd_fact_basis or "").strip()
        if basis and basis not in ("명시 없음",) and not basis.startswith("http"):
            fact = _highlight_keywords(basis.replace("|", "\\|"), hl_kws)
        elif _is_http_url(url):
            fact = _md_link("원문", url)
        else:
            fact = (basis or url).replace("|", "\\|")
        lines.append(
            f"| **{score}/5** | {link} {issue} | {target} | {link_point} | {fact} |"
        )
        included_count += 1

    skipped = len(articles) - included_count
    if skipped:
        lines += [
            "",
            f"*(이하 {skipped}건은 R&D 적합 1점 또는 국내 투자 신호 미약으로 표에서 생략)*",
        ]

    lines += [
        "- **상충되는 정보:** (해당 없음)",
        "",
        "---",
        "",
    ]
    return lines


def _build_rd_daily_stats(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None = None,
) -> str:
    """Factual collection breakdown — no interpretive daily theme."""
    kws = top_keywords or []
    scores = [compute_rd_match_score(a, kws) for a in articles]
    high = sum(1 for s in scores if s >= 4)
    mid = sum(1 for s in scores if s == 3)
    low = sum(1 for s in scores if s == 2)
    one = sum(1 for s in scores if s == 1)

    parts = [f"R&D 적합 4점+ {high}건", f"3점 {mid}건", f"2점 {low}건"]
    if one:
        parts.append(f"1점 {one}건")

    actors: list[str] = []
    for article in articles:
        fields = parse_rd_fields(article.ko_summary_steps)
        actor = (fields.get("investment_actor") or "").strip()
        if actor and actor not in ("명시 없음", "해당 없음"):
            actors.append(actor)
    if actors:
        unique = list(dict.fromkeys(actors))
        shown = unique[:3]
        suffix = " 등" if len(unique) > 3 else ""
        parts.append(f"투자 주체 명시 {len(actors)}건 ({', '.join(shown)}{suffix})")

    return " · ".join(parts)


# Backward-compatible alias for HTML dashboard import.
_build_rd_daily_theme = _build_rd_daily_stats


def _build_item_block(
    article: SummarizedArticle,
    index: int,
    log_date: date,
    top_keywords: list[str] | None,
    slug: str,
) -> list[str]:
    material = _material_type(article)
    credibility = _credibility(article)
    tags = _infer_tags(article)
    hl_kws = _keywords_for_highlight(article, top_keywords)
    summary_lines = [
        _highlight_keywords(line, hl_kws)
        for line in _build_summary_lines(article, top_keywords)
    ]

    note_parts: list[str] = []
    if is_gov_target(article):
        note_parts.append("우선: 정부·R&D 타깃 (프라운호퍼 협력 관점)")
    if top_keywords:
        marked = ", ".join(f"<mark>{kw}</mark>" for kw in top_keywords)
        note_parts.append(f"분석 키워드: {marked}")
    level = _classify_relevance(article, top_keywords or [])
    if level != "none":
        note_parts.append(f"키워드 관련도: {_RELEVANCE_LABEL[level]}")
    if article.matched_keywords:
        marked_matches: list[str] = []
        skip = gov_target_pass_label()
        for kw in article.matched_keywords[:3]:
            if kw == skip:
                marked_matches.append(kw)
            else:
                marked_matches.append(f"<mark>{kw}</mark>")
        note_parts.append(f"매칭: {', '.join(marked_matches)}")
    note = " · ".join(note_parts) if note_parts else ""

    heading_title = article.title.replace("…", "").replace("...", "").strip()
    heading_title = _highlight_keywords(heading_title, hl_kws)
    source_name = format_source_display_name(article.source_name) or "출처"
    url = _article_url(article)
    heading_title = _link_text(heading_title, url)

    linked_summary: list[str] = []
    for idx, line in enumerate(summary_lines):
        if idx == 0 and _is_http_url(url) and not line.startswith("(해석)"):
            linked_summary.append(_link_text(line, url))
        else:
            linked_summary.append(line)

    lines = [
        _item_anchor_tag(slug),
        f"### {_time_label(article, index)} {heading_title}",
        "",
        f"- **자료유형:** {material}",
        f"- **출처:** {source_name}",
        f"- **저자/발행기관:** {source_name}",
        f"- **발행일:** {_published_date(article, log_date)}",
        f"- **링크/DOI:** {url if url else '—'}",
    ]

    lines.append("- **요약:**")
    for line in linked_summary:
        lines.append(f"  - {line}")

    rd_lines = build_rd_targeting_block(article, top_keywords)
    if rd_lines:
        lines.append("")
        lines.extend(_highlight_after_md_label(line, hl_kws) for line in rd_lines)

    lines += [
        f"- **신뢰도:** {credibility}",
        f"- **태그:** {' '.join(tags)}",
    ]
    if note:
        lines.append(f"- **비고:** {note}")
    lines.append("")
    return lines


def _build_low_relevance_section(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None,
    start_index: int,
) -> list[str]:
    """Compact appendix for weak/none items — title + source + link only."""
    if not articles:
        return []
    kws = top_keywords or []
    lines = [
        "## 관련도 낮음 (참고)",
        "",
        "모니터링 키워드와 직접·간접 연관이 약해 "
        "본문에서 제외한 항목임. 필요 시 원문만 확인.",
        "",
    ]
    for offset, article in enumerate(articles):
        index = start_index + offset
        level = _classify_relevance(article, kws)
        level_ko = RELEVANCE_LABEL_KO.get(level, level)
        title = article.title.replace("…", "").replace("...", "").strip()
        url = _article_url(article)
        title_part = _link_text(title, url) if _is_http_url(url) else title
        lines.append(
            f"{index}. [{level_ko}] {title_part} — "
            f"{format_source_display_name(article.source_name)}"
        )
    lines.append("")
    return lines


def _build_markdown(
    log_date: date,
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None,
    recorder: str | None,
) -> str:
    kws = top_keywords or []
    sorted_all = _sort_articles_by_relevance(articles, kws) if articles else []
    primary = [
        a for a in sorted_all if _classify_relevance(a, kws) in ("direct", "indirect")
    ]
    low = [
        a for a in sorted_all if _classify_relevance(a, kws) in ("weak", "none")
    ]

    buckets = Counter(_homepage_bucket(_material_type(a)) for a in primary)
    article_count = buckets.get("기사", 0)
    press_count = buckets.get("보도자료", 0)
    paper_count = buckets.get("논문", 0)

    cred_counts = Counter(_credibility_grade(_credibility(a)) for a in primary)
    author = recorder or os.getenv("DAILY_LOG_RECORDER", "Tech Market Monitor (auto)")

    iso = log_date.isoformat()
    header_total = (
        f"총 항목 수: {len(primary)}건 "
        f"(기사 {article_count} / 보도자료 {press_count} / 논문 {paper_count})"
    )
    if low:
        header_total += f" · 관련도 낮음 {len(low)}건은 참고 섹션"

    lines: list[str] = [
        "# 국내 R&D 인텔리전스 데일리 로그",
        "",
        f"날짜: {iso}",
        f"기록자: {author}",
        header_total,
        f"신뢰도 분포: A {cred_counts.get('A', 0)}건 / B {cred_counts.get('B', 0)}건 / C {cred_counts.get('C', 0)}건",
        "",
    ]

    if primary:
        article_slugs = _build_item_slugs(primary)
        lines += _build_executive_summary(primary, top_keywords, article_slugs)
    else:
        article_slugs = {}
        if kws:
            kw_header = format_monitoring_keyword_header(kws)
            lines += [
                "## 오늘의 R&D 인텔리전스 요약",
                "",
                f"**모니터링 키워드:** {kw_header}",
                "",
                "오늘 직접·간접 관련 수집 항목 없음"
                + (f" (관련도 낮은 {len(low)}건은 아래 참고 섹션)." if low else "."),
                "",
            ]
        elif not low:
            lines += ["(해당일 수집·관련 항목 없음)", ""]

    lines += ["## 항목 기록", ""]

    if primary:
        for index, article in enumerate(primary, start=1):
            lines += _build_item_block(
                article, index, log_date, top_keywords, article_slugs[article.url]
            )
    else:
        lines += ["(직접·간접 관련 항목 없음)", ""]

    lines += _build_low_relevance_section(low, top_keywords, start_index=len(primary) + 1)

    lines += [
        "---",
        "",
        *credibility_legend_lines(),
    ]

    return "\n".join(lines)


RELEVANCE_LABEL_KO = {"direct": "직접", "indirect": "간접", "weak": "약함", "none": "없음"}


def classify_keyword_relevance(
    article: SummarizedArticle,
    top_keywords: list[str] | None = None,
) -> str:
    """Public wrapper for daily/monthly keyword relevance (direct/indirect/weak/none)."""
    return _classify_relevance(article, top_keywords or [])


def keyword_relevance_label(level: str) -> str:
    return RELEVANCE_LABEL_KO.get(level, "없음")
