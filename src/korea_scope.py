from __future__ import annotations

import re
from urllib.parse import urlparse

from src.models import FilteredArticle, RawArticle, SummarizedArticle
from src.policy_priority import is_gov_target, is_official_government_source

# Non-Korean hosts — drop regardless of keyword match.
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
    "electrek.co",
    "venturebeat.com",
    "technologyreview.com",
    "google.com",
    "blog.google",
)

_KOREA_SCOPE = re.compile(
    r"한국|대한민국|국내|내수|K-?표준|Korea(?:n)?(?!\s+(?:Times|Herald|Z\b))"
    r"|서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
    r"|과기정통부|과학기술정보통신부|산업통상|산업부|MOTIE|MSIT|IITP|KISTEP|KIPO|ETRI|KAIST|POSTECH"
    r"|한국전력|KEPCO|한전|한국가스|KOGAS|한국수력|KHNP"
    r"|삼성|SK하이닉스|SK\s*그룹|LG(?:전자|에너지|디스플레이)?|현대|포스코|HD현대|두산|LS\s*일렉트릭"
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


def is_korea_scoped(article: RawArticle | FilteredArticle | SummarizedArticle) -> bool:
    """True when the article is domestically scoped to the Republic of Korea."""
    if getattr(article, "category", "") != "korean":
        return False

    if is_foreign_url(article.url):
        return False

    if is_official_government_source(article) or is_gov_target(article):
        return True

    text = _article_text(article)
    if _KOREA_SCOPE.search(text):
        return True

    # Korean-language domestic media about a foreign-only subject — exclude.
    if _FOREIGN_HEADLINE.search(article.title) and not _KOREA_SCOPE.search(text):
        return False

    # English-only headline with no Korea anchor (e.g. preprint reprints).
    if not re.search(r"[가-힣]", article.title) and not _KOREA_SCOPE.search(text):
        return False

    return False
