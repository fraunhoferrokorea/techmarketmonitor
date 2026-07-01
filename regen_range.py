"""Re-summarize daily reports for a date range (skips already-updated rows)."""
from __future__ import annotations

import sys
from datetime import date, timedelta

from regen_daily_report import regen_daily_report


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    start = date.fromisoformat(args[0]) if len(args) > 0 else date(2026, 6, 21)
    end = date.fromisoformat(args[1]) if len(args) > 1 else date(2026, 6, 29)
    resume = "--no-resume" not in flags

    d = start
    while d <= end:
        print(f"\n=== {d.isoformat()} ===", flush=True)
        try:
            regen_daily_report(d, fetch_urls="--fetch" in flags, resume=resume)
        except SystemExit as exc:
            print(f"SKIP {d}: {exc}", flush=True)
        d += timedelta(days=1)


if __name__ == "__main__":
    main()
