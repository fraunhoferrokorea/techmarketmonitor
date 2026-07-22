"""Remove Herald duplicate of YNA Taihan award; set investment actors; rebuild dailies."""
from __future__ import annotations

import re
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from src.config import load_settings
from src.daily_report import log_to_summarized_article
from src.daily_sync import rebuild_markdown_from_db
from src.storage import DailyLogStore

HERALD_URL_FRAGMENT = "heraldcorp.com/article/10773310"
ACTORS = {
    "electimes.com": "한국전력공사, LS전선, 대한전선, 일진전기",
    "yna.co.kr": "대한전선, 한국전력공사",
}


def main() -> None:
    settings = load_settings()
    store = DailyLogStore(settings.database_path)

    with store._connect() as conn:
        cur = conn.execute(
            "DELETE FROM daily_logs WHERE url LIKE ?",
            (f"%{HERALD_URL_FRAGMENT}%",),
        )
        print(f"deleted_herald={cur.rowcount}")

    for log_date in (date(2026, 6, 11), date(2026, 6, 17)):
        rows = store.get_entries_for_date(log_date)
        for row in rows:
            url = row.get("url") or ""
            actor = next((name for host, name in ACTORS.items() if host in url), None)
            if not actor:
                continue
            art = log_to_summarized_article(row)
            steps = list(art.ko_summary_steps or [])
            out: list[str] = []
            replaced = False
            for step in steps:
                # parse_rd_fields requires **투자 주체:** markdown heading
                if re.match(r"^\*?\*?투자 주체:?\*?\*?\s*", step):
                    out.append(f"**투자 주체:** {actor}")
                    replaced = True
                elif re.match(r"^\*?\*?투자 목적:?\*?\*?\s*", step):
                    content = re.sub(r"^\*?\*?투자 목적:?\*?\*?\s*", "", step).strip()
                    out.append(f"**투자 목적:** {content}")
                elif re.match(r"^\*?\*?팩트 근거:?\*?\*?\s*", step):
                    content = re.sub(r"^\*?\*?팩트 근거:?\*?\*?\s*", "", step).strip()
                    out.append(f"**팩트 근거:** {content}")
                else:
                    out.append(step)
            if not replaced:
                out.insert(0, f"**투자 주체:** {actor}")
            store.update_summarized_entry(row["id"], replace(art, ko_summary_steps=out))
            print(f"updated actor {log_date} -> {actor}")
        path = rebuild_markdown_from_db(log_date, store, settings, repolish_db=False)
        print(f"rebuilt {path}")


if __name__ == "__main__":
    main()
