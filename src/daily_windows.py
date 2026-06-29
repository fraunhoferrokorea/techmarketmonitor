from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DAILY_RUN_HOUR = 8
DAILY_RUN_MINUTE = 0


def now_kst() -> datetime:
    return datetime.now(tz=KST)


def window_end_for_log_date(log_date: date, now: datetime) -> datetime:
    """Define the article collection window end for a report date."""
    today = now.date()
    if log_date >= today:
        return now

    return datetime.combine(
        log_date + timedelta(days=1),
        time(DAILY_RUN_HOUR, DAILY_RUN_MINUTE),
        tzinfo=KST,
    )
