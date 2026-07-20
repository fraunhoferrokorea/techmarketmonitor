"""Catch-up must retry calendar holes and not finalize today early."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import src.catchup as catchup_mod
import src.daily_report as daily_report_mod
from src.catchup import owed_log_dates
from src.daily_report import is_empty_daily_report, save_empty_daily_report
from src.storage import DailyLogStore


KST = ZoneInfo("Asia/Seoul")


def test_owed_log_dates_excludes_today_and_finds_holes(tmp_path, monkeypatch):
    report_dir = tmp_path / "daily"
    report_dir.mkdir()
    db_path = tmp_path / "monitor.db"

    present = {date(2026, 7, 10), date(2026, 7, 13)}
    for d in present:
        (report_dir / f"daily_{d.isoformat()}.md").write_text("# ok\n", encoding="utf-8")

    monkeypatch.setattr(catchup_mod, "report_dates_from_disk", lambda: sorted(present))
    monkeypatch.setattr(
        catchup_mod,
        "load_last_completed_log_date",
        lambda: date(2026, 7, 19),
    )
    monkeypatch.setattr(
        catchup_mod,
        "report_exists",
        lambda d: (report_dir / f"daily_{d.isoformat()}.md").is_file(),
    )

    store = DailyLogStore(db_path)
    now = datetime(2026, 7, 20, 8, 0, tzinfo=KST)
    owed = owed_log_dates(now, store=store)

    assert date(2026, 7, 20) not in owed
    assert date(2026, 7, 11) in owed
    assert date(2026, 7, 12) in owed
    assert date(2026, 7, 10) not in owed
    assert date(2026, 7, 13) not in owed


def test_empty_daily_report_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_report_mod, "_OUTPUT_BASE", tmp_path)
    path = save_empty_daily_report(
        date(2026, 7, 11),
        output_dir=tmp_path,
        top_keywords=["전력계통", "스마트그리드", "파워그리드"],
    )
    assert path.is_file()
    assert is_empty_daily_report(date(2026, 7, 11), output_dir=tmp_path)
