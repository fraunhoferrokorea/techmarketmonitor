#!/usr/bin/env python3
"""Build GitHub Pages HTML from daily markdown reports."""
from __future__ import annotations

from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "output" / "daily"

_REPORT_SHELL = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
body {{ font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; max-width: 960px; margin: 0 auto; padding: 1.5rem; color: #1a1a1a; }}
a {{ color: #0969da; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.92rem; }}
th, td {{ border: 1px solid #d0d7de; padding: 0.5rem 0.75rem; text-align: left; vertical-align: top; }}
th {{ background: #f6f8fa; }}
h1 {{ border-bottom: 1px solid #d0d7de; padding-bottom: 0.3rem; }}
.nav {{ margin-bottom: 1.5rem; font-size: 0.95rem; }}
mark {{ background: #fff3bf; color: inherit; padding: 0 0.15em; border-radius: 2px; }}
</style>
</head>
<body>
<p class="nav"><a href="index.html">← 날짜 목록</a></p>
<div class="report">{content}</div>
</body>
</html>
"""

_INDEX_SHELL = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>국내 R&D 인텔리전스 · 데일리 리포트</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }}
h1 {{ font-size: 1.5rem; }}
ul {{ line-height: 2; }}
.latest {{ background: #f6f8fa; padding: 1rem; border-radius: 8px; margin-bottom: 1.5rem; }}
</style>
</head>
<body>
<h1>국내 R&D 인텔리전스 · 데일리 리포트</h1>
<p>프라운호퍼 한국 · GitHub Pages</p>
<div class="latest"><strong>최신:</strong> <a href="daily_{latest}.html">{latest}</a></div>
<ul>
{rows}
</ul>
</body>
</html>
"""


def main() -> None:
    md_files = sorted(DAILY_DIR.glob("daily_*.md"), reverse=True)
    if not md_files:
        print("No daily markdown files found.")
        return

    index_rows: list[str] = []
    for md_path in md_files:
        iso = md_path.stem.replace("daily_", "")
        html_name = f"daily_{iso}.html"
        md_text = md_path.read_text(encoding="utf-8")
        body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
        html = _REPORT_SHELL.format(title=f"Daily {iso}", content=body)
        (DAILY_DIR / html_name).write_text(html, encoding="utf-8")
        index_rows.append(f"<li><a href=\"{html_name}\">{iso}</a></li>")

    latest = md_files[0].stem.replace("daily_", "")
    (DAILY_DIR / "index.html").write_text(
        _INDEX_SHELL.format(latest=latest, rows="\n".join(index_rows)),
        encoding="utf-8",
    )
    print(f"Built {len(md_files)} report page(s) + index.html")


if __name__ == "__main__":
    main()
