from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from src.models import FilteredArticle, RawArticle, SummarizedArticle
from src.policy_priority import is_gov_target, is_official_government_source

logger = logging.getLogger(__name__)

# Non-Korean hosts — always drop, even if a Korean RSS feed links out to them.
_FOREIGN_URL_HOSTS = (
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "ssrn.com",
    "ft.com",
    "financialtimes.com",
    "reuters.com",
    "bloomberg.com",
    "techcrunch.com",
    "theverge.com",
    "wired.com",
    "ieee.org",
    "nature.com",
    "science.org",
    "pv-magazine.com",
    "pv-magazine.de",
    "electrek.co",
    "venturebeat.com",
    "technologyreview.com",
    "google.com",
    "blog.google",
    "cnbc.com",
    "wsj.com",
    "nytimes.com",
    "bbc.com",
    "bbc.co.uk",
    "apnews.com",
    "forbes.com",
    "economist.com",
    "cleantechnica.com",
    "energy-storage.news",
    "insideevs.com",
    "techradar.com",
    "theguardian.com",
    "axios.com",
    "businessinsider.com",
    "yahoo.com",
    "msn.com",
    "reddit.com",
    "medium.com",
    "substack.com",
    "youtube.com",
    "youtu.be",
)

# Known Korean news / public hosts (may not end in .kr).
_KOREAN_MEDIA_HOSTS = (
    "yna.co.kr",
    "newsis.com",
    "hankyung.com",
    "etnews.com",
    "donga.com",
    "khan.co.kr",
    "fnnews.com",
    "heraldcorp.com",
    "hani.co.kr",
    "zdnet.co.kr",
    "korea.kr",
    "msit.go.kr",
    "motie.go.kr",
    "kistep.re.kr",
    "ketep.re.kr",
    "kepco.co.kr",
    "kipo.go.kr",
    "iitp.kr",
    "kiet.re.kr",
    "kisdi.re.kr",
    "kostat.go.kr",
    "chosun.com",
    "mk.co.kr",
    "sedaily.com",
    "mt.co.kr",
    "bloter.net",
    "boannews.com",
)

_KOREA_SCOPE = re.compile(
    r"한국|대한민국|국내|내수|K-?표준|Korea(?:n)?(?!\s+(?:Times|Herald|Z\b))"
    r"|서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|광양"
    r"|과기정통부|과학기술정보통신부|산업통상|산업부|MOTIE|MSIT|IITP|KISTEP|KIPO|ETRI|KAIST|POSTECH|KETEP"
    r"|한국전력|KEPCO|한전|한국가스|KOGAS|한국수력|KHNP"
    r"|삼성|SK하이닉스|SK\s*그룹|LG(?:전자|에너지|디스플레이)?|현대|포스코|HD현대|두산|LS\s*일렉트릭|만호제강"
    r"|NH농협|KB금융|신한|하나금융|우리금융|카카오|네이버|NAVER|쿠팡"
    r"|\.go\.kr|korea\.kr",
    re.I,
)

# Headline-led foreign scope with no Korea anchor in the full text.
_FOREIGN_HEADLINE = re.compile(
    r"(?:^|[\s\[])"
    r"(?:미국|美|EU|유럽|호주|Australia|인도|India|중국|China|일본|Japan|"
    r"독일|Germany|영국|UK|프랑스|France|캐나다|Canada|"
    r"U\.?\s*S\.?|European|Australian|Chinese|Indian|Japanese|German|British|French)"
    r"(?:[\s\]]|$|:)",
    re.I,
)

# US/local geo in English headlines — syndicated wire stories without Korea link.
_FOREIGN_GEO = re.compile(
    r"\b(?:Memphis|Tennessee|Texas|California|Long Beach|Washington D\.?C\.?|"
    r"New York|Silicon Valley|White House|Congress|Federal Reserve|"
    r"SpaceX|Starlink|Bitcoin|Ethereum|Nvidia|OpenAI|Microsoft|Apple|Google)\b",
    re.I,
)

# English-only wire-style headline with no Korean institution anchor.
_FOREIGN_SOURCE_NAMES = re.compile(
    r"bloomberg|reuters|electrek|techcrunch|the verge|wired|financial times|"
    r"associated press|cnbc|wall street journal|forbes|economist",
    re.I,
)


def _article_text(article: RawArticle | FilteredArticle | SummarizedArticle) -> str:
    parts = [article.title, article.source_name]
    summary = getattr(article, "summary", None)
    if summary:
        parts.append(summary)
    return " ".join(parts)


def _url_host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def is_foreign_url(url: str) -> bool:
    host = _url_host(url)
    if not host:
        return False
    if host.endswith(".go.kr") or host.endswith(".re.kr") or host.endswith(".or.kr"):
        return False
    return any(blocked in host for blocked in _FOREIGN_URL_HOSTS)


def is_korean_media_host(host: str) -> bool:
    if not host:
        return False
    host = host.lower().removeprefix("www.")
    if host.endswith((".go.kr", ".co.kr", ".or.kr", ".re.kr")) or host.endswith(".kr"):
        return True
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in _KOREAN_MEDIA_HOSTS)


def is_domestic_news(article: RawArticle | FilteredArticle | SummarizedArticle) -> bool:
    """True when the article is domestic Korean news suitable for Fraunhofer R&D monitoring."""
    return is_korea_scoped(article)


def is_korea_scoped(article: RawArticle | FilteredArticle | SummarizedArticle) -> bool:
    """True when the article is domestically scoped to the Republic of Korea."""
    if getattr(article, "category", "") != "korean":
        return False

    url = article.url or ""
    host = _url_host(url)

    if is_foreign_url(url):
        return False

    text = _article_text(article)
    has_korea_anchor = bool(_KOREA_SCOPE.search(text))
    has_hangul = bool(re.search(r"[가-힣]", article.title))

    if is_official_government_source(article) or is_gov_target(article):
        if is_korean_media_host(host) or has_korea_anchor:
            return True
        return False

    if _FOREIGN_SOURCE_NAMES.search(article.source_name):
        return False

    if not is_korean_media_host(host):
        return False

    if _FOREIGN_HEADLINE.search(article.title) and not has_korea_anchor:
        return False

    if _FOREIGN_GEO.search(article.title) and not has_korea_anchor and not has_hangul:
        return False

    if has_hangul:
        return True

    if has_korea_anchor:
        return True

    if not re.search(r"[가-힣]", article.title) and not has_korea_anchor:
        return False

    return False


def filter_domestic_articles(
    articles: list[RawArticle],
    *,
    label: str = "articles",
) -> tuple[list[RawArticle], int]:
    """Keep only domestic Korean news; return (kept, dropped_count)."""
    kept: list[RawArticle] = []
    dropped = 0
    for article in articles:
        if is_domestic_news(article):
            kept.append(article)
        else:
            dropped += 1
            logger.debug(
                "Excluded non-domestic %s: %s (%s)",
                label,
                article.title[:80],
                article.url[:120],
            )
    if dropped:
        logger.info(
            "Domestic news filter (%s): %d kept, %d foreign/non-domestic excluded",
            label,
            len(kept),
            dropped,
        )
    return kept, dropped
