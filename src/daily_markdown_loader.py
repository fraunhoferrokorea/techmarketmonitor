from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_REPORT_FILENAME = re.compile(r"^daily_(\d{4}-\d{2}-\d{2})\.md$")
_ITEM_HEADER = re.compile(r"^###\s+(?:(\d{2}:\d{2})\s+)?(.+)$")
_FIELD_LINE = re.compile(r"^- \*\*(.+?):\*\*\s*(.*)$")
_SUMMARY_BULLET = re.compile(r"^\s+-\s+(.*)$")

_MATERIAL_TO_CATEGORY = {
    "논문": "academic",
    "기사": "tech_news",
    "보고서(시장조사)": "enterprise",
    "공식발표(IR·정책)": "enterprise",
}
_MARK_TAG_RE = re.compile(r"</?mark>", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def _strip_mark_tags(text: str) -> str:
    return _MARK_TAG_RE.sub("", text)


def _extract_md_href(value: str) -> str:
    """Prefer href from `[label](url)`; keep bare URLs for older daily logs."""
    value = (value or "").strip()
    match = _MD_LINK_RE.search(value)
    if match:
        return match.group(2).strip()
    return value


def _extract_md_label(value: str) -> str:
    """Prefer link label from `[label](url)`; keep plain text otherwise."""
    value = (value or "").strip()
    match = re.fullmatch(r"\[([^\]]*)\]\((https?://[^)\s]+)\)", value)
    if match:
        return match.group(1).strip() or match.group(2).strip()
    return value


def load_logs_from_daily_markdown(
    year: int,
    month: int,
    daily_dir: Path | None = None,
) -> list[dict]:
    """Load monthly report entries from daily markdown files for the given month."""
    base = daily_dir or Path(__file__).resolve().parent.parent / "output" / "daily"
    if not base.is_dir():
        return []

    prefix = f"daily_{year:04d}-{month:02d}-"
    paths = sorted(base.glob(f"{prefix}*.md"))
    logs: list[dict] = []

    for path in paths:
        match = _REPORT_FILENAME.match(path.name)
        if not match:
            continue
        log_date = date.fromisoformat(match.group(1))
        entries = parse_daily_report(path, log_date=log_date)
        logs.extend(entries)
        logger.info("Loaded %d item(s) from %s", len(entries), path.name)

    return logs


def parse_daily_report(path: Path, log_date: date | None = None) -> list[dict]:
    """Parse a daily research log markdown file into monthly-ready log dicts."""
    text = path.read_text(encoding="utf-8")
    resolved_date = log_date or _parse_header_date(text) or _date_from_filename(path)
    if resolved_date is None:
        logger.warning("Could not determine log date for %s", path.name)
        return []

    items_section = _extract_items_section(text)
    if not items_section:
        return []

    entries: list[dict] = []
    for block in _split_item_blocks(items_section):
        entry = _parse_item_block(block, resolved_date)
        if entry:
            entries.append(entry)
    return entries


def _date_from_filename(path: Path) -> date | None:
    match = _REPORT_FILENAME.match(path.name)
    if not match:
        return None
    return date.fromisoformat(match.group(1))


def _parse_header_date(text: str) -> date | None:
    match = re.search(r"^날짜:\s*(\d{4}-\d{2}-\d{2})\s*$", text, re.MULTILINE)
    if not match:
        return None
    return date.fromisoformat(match.group(1))


def _extract_items_section(text: str) -> str:
    start = text.find("## 항목 기록")
    if start == -1:
        return ""

    section = text[start + len("## 항목 기록") :]
    for marker in ("---", "## 태그 분류체계"):
        idx = section.find(marker)
        if idx != -1:
            section = section[:idx]
            break
    return section.strip()


def _split_item_blocks(section: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []

    for line in section.splitlines():
        if line.startswith("### "):
            if current:
                blocks.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)

    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def _parse_item_block(block: str, log_date: date) -> dict | None:
    lines = block.splitlines()
    if not lines:
        return None

    header_match = _ITEM_HEADER.match(lines[0])
    if not header_match:
        return None

    title = _strip_mark_tags(header_match.group(2).strip())
    fields: dict[str, str] = {}
    summary_lines: list[str] = []
    in_summary = False

    for line in lines[1:]:
        if in_summary:
            bullet = _SUMMARY_BULLET.match(line)
            if bullet:
                summary_lines.append(_strip_mark_tags(bullet.group(1).strip()))
                continue
            if line.strip() == "":
                continue
            if line.startswith("- **"):
                in_summary = False
            else:
                continue

        field_match = _FIELD_LINE.match(line)
        if not field_match:
            continue

        label, value = field_match.group(1).strip(), field_match.group(2).strip()
        if label.startswith("요약"):
            in_summary = True
            continue
        fields[label] = value

    url = _extract_md_href(fields.get("링크/DOI", ""))
    if not url or not title:
        return None

    material = fields.get("자료유형", "기사")
    category = _MATERIAL_TO_CATEGORY.get(material, "tech_news")
    source_name = _extract_md_label(
        fields.get("출처", fields.get("저자/발행기관", ""))
    )
    credibility = fields.get("신뢰도", "B")
    published_at = _parse_published_at(fields.get("발행일", ""), log_date)

    ko_steps, key_trends = _split_summary_lines(summary_lines)
    llm_summary = ko_steps[0] if ko_steps else title
    matched_keywords = _parse_matched_keywords(fields.get("비고", ""))

    return {
        "log_date": log_date.isoformat(),
        "title": title,
        "url": url,
        "source_name": source_name,
        "category": category,
        "published_at": published_at,
        "matched_keywords": matched_keywords,
        "llm_summary": llm_summary,
        "key_trends": key_trends,
        "ko_summary_steps": ko_steps,
        "en_summary_steps": [],
        "report_credibility": _credibility_grade(credibility),
    }


def _parse_published_at(raw: str, fallback: date) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return fallback.isoformat()


def _split_summary_lines(summary_lines: list[str]) -> tuple[list[str], list[str]]:
    ko_steps: list[str] = []
    key_trends: list[str] = []

    for line in summary_lines:
        if line.startswith("(해석)"):
            interpretation = line.removeprefix("(해석)").strip()
            if interpretation.endswith(" 흐름과 연결되는 시장 신호로 보임"):
                trend = interpretation.removesuffix(" 흐름과 연결되는 시장 신호로 보임").strip()
                if trend:
                    key_trends.append(trend)
            elif interpretation:
                key_trends.append(interpretation)
            continue
        ko_steps.append(line)

    return ko_steps, key_trends


def _parse_matched_keywords(note: str) -> list[str]:
    match = re.search(r"매칭:\s*(.+?)(?:\s*·|$)", note)
    if not match:
        return []
    return [
        _strip_mark_tags(part.strip())
        for part in match.group(1).split(",")
        if part.strip()
    ]


def _credibility_grade(raw: str) -> str:
    raw = raw.strip()
    return raw[0] if raw else "B"
