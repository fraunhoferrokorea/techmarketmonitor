from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "daily_scheduler_state.json"
_REPORT_DIR = Path(__file__).resolve().parent.parent / "output" / "daily"
_REPORT_PATTERN = re.compile(r"^daily_(\d{4}-\d{2}-\d{2})\.md$")


def report_path(log_date: date) -> Path:
    return _REPORT_DIR / f"daily_{log_date.isoformat()}.md"


def report_exists(log_date: date) -> bool:
    return report_path(log_date).is_file()


def remove_report(log_date: date) -> bool:
    """Delete the daily markdown file for log_date if it exists."""
    path = report_path(log_date)
    if not path.is_file():
        return False
    path.unlink()
    return True


def report_dates_from_disk() -> list[date]:
    dates: list[date] = []
    for path in _REPORT_DIR.glob("daily_*.md"):
        match = _REPORT_PATTERN.match(path.name)
        if match:
            dates.append(date.fromisoformat(match.group(1)))
    return dates


def load_last_completed_log_date() -> date | None:
    if not _STATE_FILE.is_file():
        return _infer_last_completed_log_date()

    try:
        payload = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        raw = payload.get("last_completed_log_date")
        if not raw:
            legacy = payload.get("last_completed_schedule_date")
            if legacy:
                return date.fromisoformat(legacy) - timedelta(days=1)
            return _infer_last_completed_log_date()
        return date.fromisoformat(raw)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Invalid scheduler state file (%s); inferring from reports", exc)
        return _infer_last_completed_log_date()


def save_last_completed_log_date(log_date: date) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps({"last_completed_log_date": log_date.isoformat()}, indent=2),
        encoding="utf-8",
    )


def _infer_last_completed_log_date() -> date | None:
    latest_log_date: date | None = None
    for path in _REPORT_DIR.glob("daily_*.md"):
        match = _REPORT_PATTERN.match(path.name)
        if not match:
            continue
        log_date = date.fromisoformat(match.group(1))
        if latest_log_date is None or log_date > latest_log_date:
            latest_log_date = log_date

    return latest_log_date
