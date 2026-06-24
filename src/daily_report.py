from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from src.models import SummarizedArticle
from src.summarizer import (
    normalize_korean_endings,
    normalize_korean_endings_sentences,
    polish_korean,
    strip_cjk_from_korean,
)

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


def _build_summary_lines(
    article: SummarizedArticle,
    top_keywords: list[str] | None = None,
) -> list[str]:
    steps = article.ko_summary_steps or article.en_summary_steps
    facts: list[str] = []

    for step in steps:
        cleaned = polish_korean(strip_cjk_from_korean(_strip_heading(step)))
        cleaned = re.sub(r"\[\d+\]\s*$", "", cleaned).strip()
        cleaned = normalize_korean_endings_sentences(cleaned)
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
    return f"{_time_label(article, index)} {article.title}"


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


def _item_summary_link(article: SummarizedArticle, slug: str, max_len: int = 45) -> str:
    short = article.title[:max_len] + ("…" if len(article.title) > max_len else "")
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


def _keyword_connection(
    article: SummarizedArticle,
    top_keywords: list[str],
    level: str,
) -> str:
    kws = top_keywords[:3]
    kw_label = " · ".join(kws)
    if level == "direct":
        hit = [kw for kw in kws if kw in _article_text_blob(article)]
        target = ", ".join(hit[:2]) if hit else kw_label
        return f"→ **[{target}]** 직접 연관"
    if level == "indirect":
        return f"→ **[{kw_label}]** 간접 연관 ({_indirect_reason(article)})"
    return f"→ **[{kw_label}]** 관련성 낮음"


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

    Always prefers ko_summary_steps (actual article content) over
    keyword_relevance, which may contain cross-article boilerplate.
    Sentences must name their subject explicitly — deictic openers
    ('이 프레임워크', '이는', '새로운 프레임워크') are skipped.
    """
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
            sort_key = (
                _has_deictic_subject(sentence) or _has_deictic_reference(sentence),
                -anchor_hits,
                -_kw_score(sentence, top_keywords),
                _STEP_PREF.get(idx, 9),
            )
            ranked.append((sort_key, sentence))

    ranked.sort(key=lambda x: x[0])
    for _, best in ranked:
        return normalize_korean_endings(best)

    if article.llm_summary:
        headline = re.sub(r"\s*Source:.*$", "", article.llm_summary, flags=re.IGNORECASE).strip()
        if headline and not _is_vague(_first_sentence(headline)):
            return normalize_korean_endings(_first_sentence(headline))
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

    A sentence is considered vague when it:
    - Starts with a deictic subject ('이 프레임워크', '이는', …).
    - Is shorter than the informative minimum (lower for named entities/numbers).
    - Matches one of the _VAGUE_PATTERNS (generic filler phrases).
    """
    s = sentence.strip()
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


def _build_keyword_signals(
    items: list[tuple[SummarizedArticle, str, str, str]],
    top_keywords: list[str],
) -> list[str]:
    """Build up to 3 keyword-focused signals from direct/indirect items."""
    signals: list[str] = []
    kw_label = " · ".join(top_keywords[:3])

    for article, fact, level_label, connection in items:
        if level_label not in ("직접", "간접"):
            continue
        bracket = re.search(r"\*\*\[(.+?)\]\*\*", connection)
        kw_part = bracket.group(1) if bracket else kw_label
        short_fact = fact[:120] + ("…" if len(fact) > 120 else "")
        prefix = f"**[{kw_part}]**"
        signals.append(f"- {prefix} {short_fact}")
        if len(signals) >= 3:
            break

    if not signals:
        for article, fact, level_label, connection in items[:3]:
            short_fact = fact[:120] + ("…" if len(fact) > 120 else "")
            signals.append(f"- **[{kw_label}]** {short_fact}")
    return signals


def _build_executive_summary(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None = None,
    article_slugs: dict[str, str] | None = None,
) -> list[str]:
    """Build a concise executive summary with explicit keyword relevance."""
    kws = top_keywords or []
    kw_header = " · ".join(kws[:3]) if kws else "(미설정)"
    theme = _build_daily_theme(articles, kws)

    sources = ", ".join(dict.fromkeys(a.source_name for a in articles[:3]))
    extra = f" 외 {len(articles) - 3}개 출처" if len(articles) > 3 else ""

    lines = [
        "## 오늘의 요약 (Daily Executive Summary)",
        "",
        f"**분석 기준 키워드 (상위 3개):** {kw_header}",
        "",
        f"**오늘의 공통 흐름:** {theme}",
        "",
        f"오늘 수집 {len(articles)}건 ({sources}{extra})",
        "",
        "**항목별 핵심 요약 (키워드 연결 포함):**",
        "",
        "| 관련도 | 항목 | 한 줄 요약 |",
        "|--------|------|-----------|",
    ]

    slugs = article_slugs or _build_item_slugs(articles)

    ranked: list[tuple[int, SummarizedArticle, str, str, str]] = []
    for article in articles:
        item = _exec_summary_item(article, kws)
        if not item:
            continue
        fact, level_label, connection = item
        level_key = next(k for k, v in _RELEVANCE_LABEL.items() if v == level_label)
        ranked.append((_RELEVANCE_ORDER[level_key], article, fact, level_label, connection))

    ranked.sort(key=lambda row: (row[0], row[1].title))

    included_items: list[tuple[SummarizedArticle, str, str, str]] = []
    for _, article, fact, level_label, connection in ranked:
        slug = slugs[article.url]
        link = _item_summary_link(article, slug)
        cell_fact = f"{fact} {connection}".replace("|", "\\|")
        lines.append(f"| **{level_label}** | {link} | {cell_fact} |")
        included_items.append((article, fact, level_label, connection))

    skipped = len(articles) - len(included_items)
    if skipped:
        lines += [
            "",
            f"*(이하 {skipped}건은 관련성 낮음 또는 키워드 무관으로 요약에서 생략)*",
        ]

    lines += ["", "**눈여겨볼 신호 (키워드 관점):**"]
    lines.extend(_build_keyword_signals(included_items, kws) or [f"- **[{kw_header}]** (해당 없음)"])
    lines += [
        "",
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
    slug: str,
) -> list[str]:
    material = _material_type(article)
    credibility = _credibility(article)
    tags = _infer_tags(article)
    summary_lines = _build_summary_lines(article, top_keywords)

    note_parts: list[str] = []
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
        article_slugs = _build_item_slugs(articles)
        lines += _build_executive_summary(articles, top_keywords, article_slugs)
    else:
        article_slugs = {}

    lines += ["## 항목 기록", ""]

    for index, article in enumerate(articles, start=1):
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
        "## 신뢰도 등급 기준",
        "",
        "- **A (높음):** 피어리뷰 학술지 논문, 1차 보도(공식발표 인용), Tier-1 통신사(Reuters/Bloomberg/AP), 정부·국제기구 통계, Tier-1 시장조사기관(Gartner/IDC/McKinsey)",
        "- **B (중간):** 프리프린트(arXiv 등 동료심사 전), 업계 전문매체, 2차 인용 보도, 기업 자체 발표(IR/보도자료)",
        "- **C (참고):** 익명 소스, 추측성 기사, 단순 재가공 콘텐츠, 미검증 블로그",
        "",
    ]

    return "\n".join(lines)
