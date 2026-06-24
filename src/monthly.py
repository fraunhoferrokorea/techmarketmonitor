from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.config import PROJECT_ROOT, load_settings
from src.daily_markdown_loader import load_logs_from_daily_markdown
from src.daily_report import prepare_logs_for_monthly
from src.report_generator import ReportGenerator

logger = logging.getLogger(__name__)

_DAILY_OUTPUT_DIR = PROJECT_ROOT / "output" / "daily"


def _delete_daily_reports(year: int, month: int) -> list[str]:
    """Delete daily markdown report files for the given year/month.

    Returns the list of deleted file names.
    """
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
    logs = load_logs_from_daily_markdown(year, month, _DAILY_OUTPUT_DIR)
    source_files = sorted(
        {
            f"daily_{entry['log_date']}.md"
            for entry in logs
            if entry.get("log_date")
        }
    )

    if not logs:
        return {
            "year": year,
            "month": month,
            "entries": 0,
            "report_path": None,
            "source": "daily_markdown",
            "source_files": [],
            "message": "No daily markdown reports found for this month.",
        }

    monthly_logs, excluded_c = prepare_logs_for_monthly(logs)
    if excluded_c:
        logger.info(
            "Excluded %d C-grade log(s) from monthly report for %04d-%02d",
            excluded_c,
            year,
            month,
        )

    if not monthly_logs:
        return {
            "year": year,
            "month": month,
            "entries": 0,
            "excluded_c_grade": excluded_c,
            "report_path": None,
            "source": "daily_markdown",
            "source_files": source_files,
            "message": "No A/B-grade entries found in daily markdown reports for this month.",
        }

    generator = ReportGenerator(settings)
    report_path = generator.generate_monthly_report(year, month, monthly_logs)
    report_path_ko = generator.generate_monthly_report_ko(year, month, monthly_logs)

    deleted_files: list[str] = []
    if cleanup_daily:
        deleted_files = _delete_daily_reports(year, month)
        logger.info(
            "Cleaned up %d daily report(s) for %04d-%02d", len(deleted_files), year, month
        )

    return {
        "year": year,
        "month": month,
        "entries": len(monthly_logs),
        "excluded_c_grade": excluded_c,
        "source": "daily_markdown",
        "source_files": source_files,
        "report_path": str(report_path),
        "report_path_ko": str(report_path_ko),
        "deleted_daily_reports": deleted_files,
    }
