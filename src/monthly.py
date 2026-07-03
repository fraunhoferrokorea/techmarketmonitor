from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

from src.config import PROJECT_ROOT, Settings, load_settings
from src.daily_markdown_loader import load_logs_from_daily_markdown
from src.daily_report import log_to_summarized_article
from src.korea_scope import is_domestic_news
from src.rd_monthly_report import generate_rd_monthly_report
from src.rd_targeting import MONTHLY_RD_MIN_SCORE
from src.storage import DailyLogStore

logger = logging.getLogger(__name__)

_DAILY_OUTPUT_DIR = PROJECT_ROOT / "output" / "daily"
_GENERATE_LEGACY_TMR = os.getenv("GENERATE_LEGACY_TMR", "").lower() in ("1", "true", "yes")


def _load_monthly_logs(
    year: int,
    month: int,
    settings: Settings,
) -> tuple[list[dict], str, list[str]]:
    """Load monthly entries from DB (Korea-only) or fall back to daily markdown."""
    store = DailyLogStore(settings.database_path)
    db_logs = store.get_logs_for_month(year, month)
    if db_logs:
        domestic: list[dict] = []
        for log in db_logs:
            if is_domestic_news(log_to_summarized_article(log)):
                domestic.append(log)
        if domestic:
            source_files = sorted(
                {f"daily_{entry['log_date']}.md" for entry in domestic if entry.get("log_date")}
            )
            logger.info(
                "Loaded %d domestic log(s) from DB for %04d-%02d",
                len(domestic),
                year,
                month,
            )
            return domestic, "database", source_files

    logs = load_logs_from_daily_markdown(year, month, _DAILY_OUTPUT_DIR)
    source_files = sorted(
        {f"daily_{entry['log_date']}.md" for entry in logs if entry.get("log_date")}
    )
    return logs, "daily_markdown", source_files


def _delete_daily_reports(year: int, month: int) -> list[str]:
    prefix = f"{year:04d}-{month:02d}-"
    deleted: list[str] = []
    if not _DAILY_OUTPUT_DIR.exists():
        return deleted

    for path in sorted(_DAILY_OUTPUT_DIR.glob(f"daily_{prefix}*.md")):
        try:
            path.unlink()
            deleted.append(path.name)
            logger.info("Deleted daily report: %s", path.name)
        except OSError as exc:
            logger.warning("Could not delete %s: %s", path.name, exc)
    return deleted


def run_monthly_report(
    year: int | None = None,
    month: int | None = None,
    cleanup_daily: bool = True,
) -> dict:
    today = date.today()
    year = year or today.year
    month = month or today.month

    settings = load_settings()
    logs, source, source_files = _load_monthly_logs(year, month, settings)

    if not logs:
        return {
            "year": year,
            "month": month,
            "entries": 0,
            "report_path": None,
            "source": source,
            "source_files": [],
            "message": "No domestic logs found for this month (DB or daily markdown).",
        }

    try:
        report_path_ko = generate_rd_monthly_report(year, month, logs, settings)
    except ValueError as exc:
        return {
            "year": year,
            "month": month,
            "entries": 0,
            "report_path": None,
            "source": source,
            "source_files": source_files,
            "message": str(exc),
        }

    report_path = None
    if _GENERATE_LEGACY_TMR:
        from src.daily_report import prepare_logs_for_monthly
        from src.report_generator import ReportGenerator

        monthly_logs, excluded_c = prepare_logs_for_monthly(logs)
        if monthly_logs:
            generator = ReportGenerator(settings)
            report_path = generator.generate_monthly_report(year, month, monthly_logs)
            logger.info("Legacy EN TMR also generated (GENERATE_LEGACY_TMR=1)")

    deleted_files: list[str] = []
    if cleanup_daily:
        deleted_files = _delete_daily_reports(year, month)

    return {
        "year": year,
        "month": month,
        "entries": len(logs),
        "rd_min_score": MONTHLY_RD_MIN_SCORE,
        "source": source,
        "source_files": source_files,
        "report_path": str(report_path_ko),
        "report_path_ko": str(report_path_ko),
        "report_path_legacy_en": str(report_path) if report_path else None,
        "deleted_daily_reports": deleted_files,
    }
