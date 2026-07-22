from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RawArticle:
    title: str
    url: str
    summary: str
    source_name: str
    category: str
    published_at: datetime | None


@dataclass(frozen=True)
class FilteredArticle:
    title: str
    url: str
    summary: str
    source_name: str
    category: str
    published_at: datetime | None
    matched_keywords: list[str]


@dataclass(frozen=True)
class SummarizedArticle:
    title: str
    url: str
    source_name: str
    category: str
    published_at: datetime | None
    matched_keywords: list[str]
    llm_summary: str
    key_trends: list[str]
    ko_summary_steps: list[str] = field(default_factory=list)
    en_summary_steps: list[str] = field(default_factory=list)
    keyword_relevance: str = ""
    ko_one_liner: str = ""
    rd_match_score: int = 0
    rd_proposable_area: str = ""
    rd_fact_basis: str = ""
    rd_evidence_quotes: list[str] = field(default_factory=list)
