from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from src.models import SummarizedArticle
from src.policy_priority import is_gov_target, gov_target_score
from src.rd_targeting import (
    build_daily_rd_insights,
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

_TIER1_NEWS = {"연합뉴스", "yna", "뉴시스", "newsis"}
_TIER1_RESEARCH = {"kistep", "kiet", "iitp", "kipo", "ketep", "kepco", "koita", "kisdi"}
_PEER_REVIEW_HINTS = {"kci", "dbpia", "ieee", "springer", "elsevier", "wiley", "nature", "science", "kisti", "etri"}
_PREPRINT_HINTS = {"arxiv", "biorxiv", "medrxiv", "ssrn", "preprint", "프리프린트"}
_GOVERNMENT_HINTS = {
    "korea.kr",
    "정책브리핑",
    "motie",
    "msit",
    "mss",
    "mw",
    "moe",
    "molit",
    "mcee",
    "mnd",
    "kasa",
    "과기정통",
    "산업통상",
    "중소벤처",
    "보건복지",
    "국토교통",
    "기후에너지",
    "우주항공",
    "kipo",
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
}

CREDIBILITY_LEGEND_A = (
    "정부·공공기관 원문(korea.kr·부처 .go.kr 보도자료), "
    "연합뉴스·뉴시스 1차 보도, "
    "공공 R&D·정책기관(KISTEP·KIET·KIPO·KETEP·한국전력 등), "
    "국내 학술지·국책연구원 동료심사 논문"
)
CREDIBILITY_LEGEND_B = (
    "국내 경제·IT 전문매체(헤럴드경제·동아일보·전자신문·ZDNet Korea 등), "
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

# GitHub renders .md but shows .html as source — link md files to Pages for live dashboard.
_DEFAULT_DASHBOARD_BASE = "https://yenaalisonhong.github.io/techmarketmonitor"


def daily_dashboard_public_url(log_date: date, base: str | None = None) -> str:
    """Public URL where the HTML dashboard renders (GitHub Pages)."""
    root = (base if base is not None else os.getenv("DAILY_DASHBOARD_BASE_URL", _DEFAULT_DASHBOARD_BASE)).strip()
    iso = log_date.isoformat()
    if root.lower() in ("", "relative", "local"):
        return f"daily_{iso}.html"
    return f"{root.rstrip('/')}/daily_{iso}.html"


def daily_markdown_github_url(log_date: date) -> str:
    """GitHub blob URL for the daily markdown (renders on github.com)."""
    repo = os.getenv("GITHUB_REPO_URL", "https://github.com/yenaalisonhong/techmarketmonitor").strip()
    iso = log_date.isoformat()
    return f"{repo.rstrip('/')}/blob/main/output/daily/daily_{iso}.md"


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
    html_path = out_dir / f"daily_{iso}.html"
    from src.daily_html_report import build_daily_html

    html_path.write_text(
        build_daily_html(log_date, articles, top_keywords, recorder),
        encoding="utf-8",
    )
    from src.daily_html_report import refresh_daily_index_html

    refresh_daily_index_html(out_dir)
    logger.info("Daily research log saved → %s (dashboard: %s)", report_path, html_path)
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


def _item_summary_link(article: SummarizedArticle, slug: str, max_len: int = 45) -> str:
    title = article.title.replace("…", "").replace("...", "").strip()
    short = _truncate_text(title, max_len)
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
    {"power system", "power grid", "smart grid", "microgrid", "grid"}
)
_POWER_INDIRECT_MATCHES = frozenset(
    {
        "data center",
        "bess",
        "battery energy storage",
        "renewable energy",
        "energy storage",
        "renewable",
    }
)
_TANGENTIAL_MATCHES = frozenset({"ai infrastructure", "supply chain"})

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


def _text_mentions_power(text: str, top_keywords: list[str]) -> bool:
    if _POWER_TEXT_HINT.search(text):
        return True
    return _kw_score(text, top_keywords) > 0


def _classify_relevance(article: SummarizedArticle, top_keywords: list[str]) -> str:
    """Classify how strongly an article relates to the top-3 tracking keywords."""
    matched = {k.lower() for k in article.matched_keywords}
    blob = _article_text_blob(article)
    non_power_topic = bool(_NON_POWER_TITLE.search(article.title))

    if non_power_topic:
        if matched & _POWER_DIRECT_MATCHES:
            return "direct"
        if matched & (_POWER_INDIRECT_MATCHES | _TANGENTIAL_MATCHES):
            return "weak"
        return "none"

    if matched & _POWER_DIRECT_MATCHES:
        return "direct"
    if _text_mentions_power(blob, top_keywords):
        return "direct"
    if _POWER_SUPPLY_HINT.search(blob):
        return "direct"
    if matched & _POWER_INDIRECT_MATCHES:
        return "indirect"
    if matched & _TANGENTIAL_MATCHES:
        if _text_mentions_power(blob, top_keywords):
            return "indirect"
        return "weak"
    if _text_mentions_power(blob, top_keywords):
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
    for kw in top_keywords[:3]:
        if kw == "전력계통":
            parts.append("전력망 안정·용량·부하")
        elif kw == "파워그리드":
            parts.append("송전·배전·피크·VPP")
        elif kw == "스마트그리드":
            parts.append("지능형 운영·분산자원·수요반응")
    return ", ".join(parts[:2]) if parts else "전력·그리드"


def _keyword_connection(
    article: SummarizedArticle,
    top_keywords: list[str],
    level: str,
) -> str:
    """Last sentence in the executive-summary row: keyword relevance rationale."""
    kws = top_keywords[:3]
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


def _extract_fact_sentence(
    article: SummarizedArticle,
    top_keywords: list[str],
    level: str,
) -> str:
    """Pick the best one-sentence fact for the executive summary.

    Prefers LLM-generated ko_one_liner (5W1H-dense), then ko_summary_steps
    ranked by informativeness. Sentences must name their subject explicitly.
    """
    if article.ko_one_liner:
        one_liner = polish_korean(
            strip_cjk_from_korean(re.sub(r"\[\d+\]\s*$", "", article.ko_one_liner).strip())
        )
        if one_liner and not _is_vague(one_liner):
            return one_liner

    anchors = _title_anchor_tokens(article.title)
    ranked: list[tuple[tuple, str]] = []

    for idx, raw in enumerate(article.ko_summary_steps):
        cleaned = polish_korean(strip_cjk_from_korean(_strip_heading(raw)))
        cleaned = re.sub(r"\[\d+\]\s*$", "", cleaned).strip()
        if not cleaned or cleaned.startswith("(해석)"):
            continue
        for sentence in _split_sentences(cleaned):
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
    kw_set = set(top_keywords[:3])

    if reason == "데이터센터 전력 부하":
        labels: list[str] = []
        if "전력계통" in kw_set:
            labels.append("**전력계통**(발전·송전 용량·피크 부하)")
        if "파워그리드" in kw_set:
            labels.append("**파워그리드**(배전망·전력 장기 구매 PPA)")
        if "스마트그리드" in kw_set:
            labels.append("**스마트그리드**(부하 예측·수요반응·피크 분산)")
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
        kws = " · ".join(top_keywords[:3])
        return f"AI 인프라 확장은 {kws} 관점의 전력 수요·공급·망 운영에 간접 영향을 줄 수 있음"

    kws = " · ".join(top_keywords[:3])
    return f"{reason} 경로로 {kws} 추적 키워드에 간접 영향 가능"


def _direct_implication_plain(top_keywords: list[str]) -> str:
    parts: list[str] = []
    for kw in top_keywords[:3]:
        if kw == "전력계통":
            parts.append("전력망 안정·용량·부하")
        elif kw == "파워그리드":
            parts.append("송전·배전·피크·VPP")
        elif kw == "스마트그리드":
            parts.append("지능형 운영·분산자원·수요반응")
    focus = ", ".join(parts[:2]) if parts else "전력·그리드"
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
    hits = [kw for kw in top_keywords[:3] if kw.lower() in blob]
    if hits:
        return " · ".join(hits[:2])
    if level_label == "직접":
        return top_keywords[0] if top_keywords else "(미설정)"
    return " · ".join(top_keywords[:3])


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
    """Build R&D intelligence executive summary (Fraunhofer Korea)."""
    kws = top_keywords or []
    kw_header = " · ".join(kws[:3]) if kws else "(미설정)"
    theme = _build_rd_daily_theme(articles, kws)

    sources = ", ".join(dict.fromkeys(a.source_name for a in articles[:3]))
    extra = f" 외 {len(articles) - 3}개 출처" if len(articles) > 3 else ""
    high_score = sum(1 for a in articles if compute_rd_match_score(a, kws) >= 4)

    lines = [
        "## 오늘의 R&D 인텔리전스 요약",
        "",
        f"**모니터링 키워드 (상위 3개):** {kw_header}",
        "",
        f"**오늘의 공통 흐름:** {theme}",
        "",
        f"오늘 수집 {len(articles)}건 (R&D 적합 4점 이상 {high_score}건) · {sources}{extra}",
        "",
        "**R&D 기회 스캔 (누가 · 왜 · 무엇을):**",
        "",
        "| R&D적합 | 핵심 이슈 | 고객 타겟 | R&D 연계 포인트 | 팩트 체크 |",
        "|---------|----------|----------|----------------|----------|",
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
        issue = _extract_fact_sentence(article, kws, "direct") or article.ko_one_liner or article.title
        issue = issue.replace("|", "\\|")
        target = (fields.get("investment_actor") or "명시 없음").replace("|", "\\|")
        link_point = format_rd_link_point(
            article.rd_proposable_area,
            fields.get("pain_point", ""),
            fields.get("investment_purpose", ""),
        ).replace("|", "\\|")
        fact = (article.rd_fact_basis or article.url).replace("|", "\\|")
        slug = slugs[article.url]
        link = _item_summary_link(article, slug, max_len=30)
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

    lines += build_daily_rd_insights(articles, kws)
    lines += [
        "- **상충되는 정보:** (해당 없음)",
        "",
        "---",
        "",
    ]
    return lines


def _build_rd_daily_theme(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None = None,
) -> str:
    kws = top_keywords or []
    scores = [compute_rd_match_score(a, kws) for a in articles]
    high = sum(1 for s in scores if s >= 4)
    mid = sum(1 for s in scores if s == 3)
    if high >= 2:
        return "국내 정부·기업의 예산·R&D 프로그램 신호가 다수 포착된 날"
    if high >= 1:
        return "국내 R&D 위탁·협력 가능성이 있는 투자·정책 이슈가 부각된 날"
    if mid >= 2:
        return "국내 산업·정책 영향은 있으나 구체적 R&D 예산 신호는 제한적인 날"
    return "국내 R&D 수주 직접 연계 신호는 약하고 배경 모니터링 위주인 날"


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
    summary_lines = _build_summary_lines(article, top_keywords)

    note_parts: list[str] = []
    if is_gov_target(article):
        note_parts.append("우선: 정부·R&D 타깃 (프라운호퍼 협력 관점)")
    if top_keywords:
        note_parts.append(f"분석 키워드: {', '.join(top_keywords[:3])}")
    level = _classify_relevance(article, top_keywords or [])
    if level != "none":
        note_parts.append(f"키워드 관련도: {_RELEVANCE_LABEL[level]}")
    if article.matched_keywords:
        note_parts.append(f"매칭: {', '.join(article.matched_keywords[:3])}")
    note = " · ".join(note_parts) if note_parts else ""

    lines = [
        _item_anchor_tag(slug),
        _item_heading_md(article, index),
        "",
        f"- **자료유형:** {material}",
        f"- **출처:** {article.source_name}",
        f"- **저자/발행기관:** {article.source_name}",
        f"- **발행일:** {_published_date(article, log_date)}",
        f"- **링크/DOI:** {article.url}",
    ]

    lines.append("- **요약:**")
    for line in summary_lines:
        lines.append(f"  - {line}")

    rd_lines = build_rd_targeting_block(article, top_keywords)
    if rd_lines:
        lines.append("")
        lines.extend(rd_lines)

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

    iso = log_date.isoformat()
    dashboard_url = daily_dashboard_public_url(log_date)
    lines: list[str] = [
        "# 국내 R&D 인텔리전스 데일리 로그",
        "",
        f"📊 **인포그래픽 대시보드 (권장):** [열기]({dashboard_url}) · [Markdown 상세 원문](daily_{iso}.md)",
        "",
        f"> GitHub에서 `.html` 파일은 코드만 보입니다. 위 **열기** 링크(GitHub Pages)로 인포그래픽을 확인하세요.",
        "",
        f"날짜: {iso}",
        f"기록자: {author}",
        f"총 항목 수: {len(articles)}건 (기사 {article_count} / 논문 {paper_count})",
        f"신뢰도 분포: A {cred_counts.get('A', 0)}건 / B {cred_counts.get('B', 0)}건 / C {cred_counts.get('C', 0)}건",
        "",
    ]

    sorted_articles = _sort_articles_by_relevance(articles, top_keywords) if articles else []

    if sorted_articles:
        article_slugs = _build_item_slugs(sorted_articles)
        lines += _build_executive_summary(sorted_articles, top_keywords, article_slugs)
    else:
        article_slugs = {}

    lines += ["## 항목 기록", ""]

    for index, article in enumerate(sorted_articles, start=1):
        lines += _build_item_block(
            article, index, log_date, top_keywords, article_slugs[article.url]
        )

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
