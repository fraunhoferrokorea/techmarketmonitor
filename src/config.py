from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

_KEYWORDS_TXT = PROJECT_ROOT / "keywords.txt"
_SOURCES_MD = PROJECT_ROOT / "sources.md"

# - **Name** — [label](https://...)
_MD_NAMED_LINK = re.compile(
    r"^\s*[-*]\s+\*\*(.+?)\*\*\s*[—–\-:]+\s*\[([^\]]*)\]\((https?://[^)\s]+)\)",
)
# - [Name](https://...)
_MD_LINK_ONLY = re.compile(
    r"^\s*[-*]\s+\[([^\]]+)\]\((https?://[^)\s]+)\)",
)
# Any remaining markdown link on a bullet/line (fallback for free-form adds)
_MD_ANY_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")

_DEFAULT_KEYWORDS: list[str] = [
    "artificial intelligence", "machine learning", "large language model",
    "generative AI", "semiconductor", "cloud computing", "cybersecurity",
    "quantum computing", "robotics", "autonomous vehicles",
]


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    deepl_api_key: str
    database_path: Path
    reports_output_dir: Path
    log_level: str
    keywords: list[str]
    keyword_labels: list[str]
    analysis_keywords: list[str]
    filter_keywords: list[str]
    keywords_path: Path


def _normalize_keyword(keyword: str) -> str:
    """Lowercase ASCII keywords for case-insensitive matching; keep Korean as-is."""
    return keyword.lower() if keyword.isascii() else keyword


def _load_keywords_config(path: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    """Load keywords.txt → (labels, normalized_for_match, analysis, filter_normalized).

    All non-comment keyword lines are used for:
    - analysis: LLM keyword_relevance, daily/monthly executive summary
    - filter: required for article collection/filter pass (gov-target exception)
    - full normalized list: RSS fetch and matched_keywords tagging
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return [], [], [], []

    labels: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        labels.append(stripped)

    normalized = [_normalize_keyword(k) for k in labels]
    return labels, normalized, labels, normalized


def _load_keywords_txt(path: Path) -> list[str]:
    """Read one keyword per line from *path*; skip blank lines and # comments."""
    labels, _, _, _ = _load_keywords_config(path)
    return labels


def _load_yaml_list(path: Path, key: str) -> list:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get(key, [])


def resolve_keywords_path() -> Path:
    """Path to keywords.txt (project root, or KEYWORDS_TXT in .env)."""
    load_dotenv(PROJECT_ROOT / ".env")
    override = os.getenv("KEYWORDS_TXT", "").strip()
    if override:
        return Path(override).expanduser()
    return _KEYWORDS_TXT


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    keywords_path = resolve_keywords_path()
    raw_labels, keywords, analysis, filter_kw = _load_keywords_config(keywords_path)
    if not keywords:
        keywords = [_normalize_keyword(k) for k in _DEFAULT_KEYWORDS]
        raw_labels = list(_DEFAULT_KEYWORDS)
        analysis = list(raw_labels)
        filter_kw = list(keywords)

    database_path = Path(os.getenv("DATABASE_PATH", "data/monitor.db"))
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path

    reports_output_dir = Path(os.getenv("REPORTS_OUTPUT_DIR", "output/monthly"))
    if not reports_output_dir.is_absolute():
        reports_output_dir = PROJECT_ROOT / reports_output_dir

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL", "gemini-2.0-flash"),
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        deepl_api_key=os.getenv("DEEPL_API_KEY", ""),
        database_path=database_path,
        reports_output_dir=reports_output_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        keywords=keywords,
        keyword_labels=raw_labels,
        analysis_keywords=analysis,
        filter_keywords=filter_kw,
        keywords_path=keywords_path,
    )


_SOURCE_GROUPS = ("korean",)


def _load_sources_md(path: Path) -> list[dict]:
    """Parse sources.md bullet links into source entries.

    Supported lines (anything else with a markdown http(s) link is also picked up):
      - **Name** — [https://example.com](https://example.com)
      - [Name](https://example.com)

    ``url`` is the browse/list page. Optional ``feed_url`` / ``method`` are merged
    from config/sources.yaml by matching ``name``. New md-only links are still
    collected using the md URL as the fetch address.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    sources: list[dict] = []
    seen_names: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        name = ""
        url = ""
        m = _MD_NAMED_LINK.match(stripped)
        if m:
            name, url = m.group(1).strip(), m.group(3).strip()
        else:
            m = _MD_LINK_ONLY.match(stripped)
            if m:
                name, url = m.group(1).strip(), m.group(2).strip()
            else:
                m = _MD_ANY_LINK.search(stripped)
                if not m:
                    continue
                label, url = m.group(1).strip(), m.group(2).strip()
                name = label or url

        if not url:
            continue
        if not name:
            name = url
        if name in seen_names:
            continue
        seen_names.add(name)
        sources.append({"name": name, "url": url, "category": "korean"})
    return sources


def _yaml_source_meta() -> dict[str, dict]:
    """Map source name → {feed_url?, method?, category?} from sources.yaml."""
    try:
        with (CONFIG_DIR / "sources.yaml").open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return {}
    meta: dict[str, dict] = {}
    for group in _SOURCE_GROUPS:
        for item in data.get(group, []) or []:
            if not item:
                continue
            name = item.get("name")
            if not name:
                continue
            entry: dict = {}
            if item.get("feed_url"):
                entry["feed_url"] = str(item["feed_url"])
            method = item.get("method")
            if method and str(method).upper() != "GET":
                entry["method"] = str(method).upper()
            if item.get("category"):
                entry["category"] = str(item["category"])
            if entry:
                meta[str(name)] = entry
    return meta


def _load_sources_yaml() -> list[dict]:
    with (CONFIG_DIR / "sources.yaml").open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    sources: list[dict] = []
    for group in _SOURCE_GROUPS:
        for item in data.get(group, []):
            sources.append(item)
    return sources


def load_sources() -> list[dict]:
    raw = _load_sources_md(_SOURCES_MD)
    if not raw:
        return _load_sources_yaml()
    meta = _yaml_source_meta()
    for entry in raw:
        extra = meta.get(entry["name"])
        if not extra:
            continue
        if "feed_url" in extra:
            entry["feed_url"] = extra["feed_url"]
        if "method" in extra:
            entry["method"] = extra["method"]
        if "category" in extra:
            entry["category"] = extra["category"]
    return raw