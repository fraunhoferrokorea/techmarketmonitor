#!/usr/bin/env python3
"""Build GitHub Pages site from daily + monthly markdown OUTPUT."""
from __future__ import annotations

import json
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "output" / "daily"
MONTHLY_DIR = ROOT / "output" / "monthly"
SITE_DIR = ROOT / "output" / "site"

_MD_EXT = ["tables", "fenced_code", "sane_lists", "smarty"]

# Fraunhofer-inspired teal institutional palette (not purple / cream-serif)
_CSS = """\
:root {
  --bg: #f3f6f5;
  --surface: #ffffff;
  --ink: #1a2421;
  --muted: #5a6b66;
  --line: #d5e0dc;
  --brand: #008878;
  --brand-dark: #006b5e;
  --brand-soft: #e6f5f2;
  --mark: #fff3bf;
  --score-high: #008878;
  --score-mid: #c47a00;
  --score-low: #8a9390;
  --shadow: 0 1px 2px rgba(26, 36, 33, 0.06), 0 8px 24px rgba(26, 36, 33, 0.06);
  --radius: 12px;
  --font: "Pretendard", "Noto Sans KR", "Segoe UI", system-ui, sans-serif;
}
*, *::before, *::after { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: var(--font);
  color: var(--ink);
  background:
    radial-gradient(1200px 500px at 10% -10%, #d8efe9 0%, transparent 55%),
    radial-gradient(900px 400px at 100% 0%, #e8eef0 0%, transparent 50%),
    var(--bg);
  line-height: 1.65;
  min-height: 100vh;
}
a { color: var(--brand-dark); text-decoration-thickness: 1px; text-underline-offset: 2px; }
a:hover { color: var(--brand); }

.app-header {
  position: sticky; top: 0; z-index: 20;
  backdrop-filter: blur(10px);
  background: rgba(243, 246, 245, 0.88);
  border-bottom: 1px solid var(--line);
}
.app-header-inner {
  max-width: 1120px; margin: 0 auto; padding: 0.85rem 1.25rem;
  display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
}
.brand {
  display: flex; align-items: center; gap: 0.75rem; min-width: 0;
}
.brand-mark {
  width: 36px; height: 36px; border-radius: 9px;
  background: linear-gradient(145deg, var(--brand), var(--brand-dark));
  color: #fff; font-weight: 700; font-size: 0.78rem;
  display: grid; place-items: center; flex-shrink: 0;
  letter-spacing: -0.02em;
}
.brand-text { min-width: 0; }
.brand-text strong { display: block; font-size: 0.98rem; letter-spacing: -0.02em; }
.brand-text span { display: block; font-size: 0.78rem; color: var(--muted); }

.layout {
  max-width: 1120px; margin: 0 auto; padding: 1.25rem;
  display: grid; grid-template-columns: 280px 1fr; gap: 1.25rem; align-items: start;
}
@media (max-width: 860px) {
  .layout { grid-template-columns: 1fr; }
}

.panel {
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); box-shadow: var(--shadow);
}
.sidebar { padding: 1rem; position: sticky; top: 72px; }
@media (max-width: 860px) { .sidebar { position: static; } }

.seg {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0.35rem;
  background: var(--brand-soft); padding: 0.3rem; border-radius: 10px; margin-bottom: 1rem;
}
.seg button {
  appearance: none; border: 0; background: transparent; color: var(--muted);
  font: inherit; font-weight: 600; font-size: 0.92rem; padding: 0.55rem 0.4rem;
  border-radius: 8px; cursor: pointer; transition: 0.15s ease;
}
.seg button.active {
  background: var(--surface); color: var(--brand-dark);
  box-shadow: 0 1px 3px rgba(0, 107, 94, 0.18);
}
.seg button:hover:not(.active) { color: var(--ink); }

.sidebar h2 {
  margin: 0 0 0.65rem; font-size: 0.78rem; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted); font-weight: 700;
}
.date-list { list-style: none; margin: 0; padding: 0; max-height: min(70vh, 640px); overflow: auto; }
.date-list li + li { margin-top: 0.25rem; }
.date-list a, .date-list button {
  width: 100%; text-align: left; appearance: none; border: 1px solid transparent;
  background: transparent; color: inherit; font: inherit; cursor: pointer;
  display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
  padding: 0.65rem 0.75rem; border-radius: 8px; text-decoration: none;
}
.date-list a:hover, .date-list button:hover { background: var(--brand-soft); }
.date-list a.active, .date-list button.active {
  background: var(--brand-soft); border-color: #b7ddd5; color: var(--brand-dark); font-weight: 600;
}
.date-list .meta { font-size: 0.75rem; color: var(--muted); white-space: nowrap; }
.empty-hint { color: var(--muted); font-size: 0.9rem; padding: 0.5rem 0.25rem; }

.main { padding: 0; min-height: 420px; overflow: hidden; }
.main-empty {
  padding: 3rem 1.5rem; text-align: center; color: var(--muted);
}
.main-empty .icon {
  width: 56px; height: 56px; margin: 0 auto 1rem; border-radius: 14px;
  background: var(--brand-soft); color: var(--brand); display: grid; place-items: center;
  font-size: 1.4rem; font-weight: 700;
}
.report-frame { border: 0; width: 100%; min-height: 70vh; display: block; }
.report-wrap { padding: 1.5rem 1.75rem 2.5rem; }

.report h1 {
  margin: 0 0 0.75rem; font-size: 1.55rem; letter-spacing: -0.03em; line-height: 1.3;
}
.report h2 {
  margin: 2rem 0 0.75rem; font-size: 1.15rem; letter-spacing: -0.02em;
  padding-bottom: 0.35rem; border-bottom: 2px solid var(--brand-soft);
}
.report h3 {
  margin: 1.5rem 0 0.6rem; font-size: 1.05rem;
  padding: 0.65rem 0.85rem; background: var(--brand-soft); border-radius: 8px;
  border-left: 4px solid var(--brand);
}
.report p { margin: 0.55rem 0; }
.report ul, .report ol { padding-left: 1.25rem; }
.report li { margin: 0.25rem 0; }
.report hr { border: 0; border-top: 1px solid var(--line); margin: 1.5rem 0; }

.report table {
  border-collapse: separate; border-spacing: 0; width: 100%;
  margin: 1rem 0; font-size: 0.9rem; overflow: hidden;
  border: 1px solid var(--line); border-radius: 10px; background: #fff;
}
.report th, .report td {
  padding: 0.65rem 0.75rem; text-align: left; vertical-align: top;
  border-bottom: 1px solid var(--line);
}
.report th { background: #eef6f4; font-weight: 650; color: var(--brand-dark); }
.report tr:last-child td { border-bottom: 0; }
.report tbody tr:hover td { background: #f7fbfa; }

mark {
  background: linear-gradient(180deg, transparent 8%, var(--mark) 8%, var(--mark) 92%, transparent 92%);
  color: inherit; padding: 0 0.12em; border-radius: 2px;
}

.stats {
  display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.85rem 0 1.25rem;
}
.chip {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.28rem 0.65rem; border-radius: 999px; font-size: 0.8rem; font-weight: 600;
  background: var(--brand-soft); color: var(--brand-dark); border: 1px solid #c5e4dd;
}
.chip.neutral { background: #f0f2f1; color: var(--muted); border-color: var(--line); }
.score {
  display: inline-block; min-width: 2.4em; text-align: center;
  padding: 0.1rem 0.45rem; border-radius: 6px; font-weight: 700; font-size: 0.85rem;
  color: #fff;
}
.score.high { background: var(--score-high); }
.score.mid { background: var(--score-mid); }
.score.low { background: var(--score-low); }

.footer-note {
  max-width: 1120px; margin: 0 auto; padding: 0 1.25rem 2rem;
  color: var(--muted); font-size: 0.8rem;
}

.back-link {
  display: inline-flex; align-items: center; gap: 0.35rem;
  margin-bottom: 1rem; font-size: 0.9rem; font-weight: 600;
}
"""

_INDEX_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Fraunhofer Korea · R&amp;D Intelligence</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin/>
<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" rel="stylesheet"/>
<style>{css}</style>
</head>
<body>
<header class="app-header">
  <div class="app-header-inner">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">Fh</div>
      <div class="brand-text">
        <strong>Fraunhofer Korea</strong>
        <span>R&amp;D Intelligence · Output Viewer</span>
      </div>
    </div>
  </div>
</header>

<div class="layout">
  <aside class="panel sidebar">
    <div class="seg" role="tablist" aria-label="리포트 종류">
      <button type="button" id="tab-daily" class="active" role="tab" aria-selected="true">Daily</button>
      <button type="button" id="tab-monthly" role="tab" aria-selected="false">Monthly</button>
    </div>
    <h2 id="list-heading">Daily 날짜</h2>
    <ul class="date-list" id="date-list"></ul>
  </aside>

  <main class="panel main" id="main">
    <div class="main-empty" id="empty-state">
      <div class="icon">OUT</div>
      <p><strong>날짜를 선택하세요</strong></p>
      <p>왼쪽에서 Daily 또는 Monthly를 고른 뒤<br/>날짜를 누르면 OUTPUT 내용이 표시됩니다.</p>
    </div>
    <div class="report-wrap" id="report-wrap" hidden>
      <div class="report" id="report"></div>
    </div>
  </main>
</div>

<p class="footer-note">OUTPUT only · keyword highlight (&lt;mark&gt;) preserved · generated from markdown reports</p>

<script>
const REPORTS = {reports_json};

function qs(id) {{ return document.getElementById(id); }}

let kind = "daily";
let currentHref = null;

function labelFor(kindName) {{
  return kindName === "daily" ? "Daily 날짜" : "Monthly 기간";
}}

function renderList() {{
  const list = qs("date-list");
  const items = REPORTS[kind] || [];
  qs("list-heading").textContent = labelFor(kind);
  if (!items.length) {{
    list.innerHTML = '<li class="empty-hint">아직 생성된 리포트가 없습니다.</li>';
    return;
  }}
  list.innerHTML = items.map((item, i) => {{
    const active = item.href === currentHref ? " active" : "";
    const meta = item.meta ? `<span class="meta">${{item.meta}}</span>` : "";
    return `<li><button type="button" class="${{active}}" data-href="${{item.href}}" data-title="${{item.title}}"><span>${{item.label}}</span>${{meta}}</button></li>`;
  }}).join("");
  list.querySelectorAll("button").forEach(btn => {{
    btn.addEventListener("click", () => loadReport(btn.dataset.href, btn.dataset.title));
  }});
}}

function setTab(next) {{
  kind = next;
  currentHref = null;
  qs("tab-daily").classList.toggle("active", kind === "daily");
  qs("tab-monthly").classList.toggle("active", kind === "monthly");
  qs("tab-daily").setAttribute("aria-selected", kind === "daily" ? "true" : "false");
  qs("tab-monthly").setAttribute("aria-selected", kind === "monthly" ? "true" : "false");
  qs("empty-state").hidden = false;
  qs("report-wrap").hidden = true;
  qs("report").innerHTML = "";
  history.replaceState(null, "", "#" + kind);
  renderList();
}}

async function loadReport(href, title) {{
  currentHref = href;
  renderList();
  qs("empty-state").hidden = true;
  qs("report-wrap").hidden = false;
  qs("report").innerHTML = "<p style='color:var(--muted)'>불러오는 중…</p>";
  history.replaceState(null, "", "#" + kind + "/" + encodeURIComponent(href));
  try {{
    const res = await fetch(href);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const body = doc.querySelector(".report");
    qs("report").innerHTML = body ? body.innerHTML : html;
    enhanceReport(qs("report"));
    document.title = (title || "Report") + " · Fraunhofer Korea";
    qs("main").scrollTop = 0;
    window.scrollTo({{ top: 0, behavior: "smooth" }});
  }} catch (err) {{
    qs("report").innerHTML = "<p>리포트를 불러오지 못했습니다. <a href=\\"" + href + "\\">새 탭에서 열기</a></p>";
  }}
}}

function enhanceReport(root) {{
  // Score chips: **3/5**, 3/5, 적합도 5/5
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  const scoreRe = /(\\d)\\s*\\/\\s*5/g;
  nodes.forEach(node => {{
    if (!node.parentElement || ["SCRIPT", "STYLE", "MARK", "A", "CODE"].includes(node.parentElement.tagName)) return;
    if (!scoreRe.test(node.nodeValue)) return;
    scoreRe.lastIndex = 0;
    const span = document.createElement("span");
    span.innerHTML = node.nodeValue.replace(scoreRe, (_, n) => {{
      const v = Number(n);
      const cls = v >= 4 ? "high" : v === 3 ? "mid" : "low";
      return `<span class="score ${{cls}}">${{n}}/5</span>`;
    }});
    node.parentElement.replaceChild(span, node);
  }});

  // Soft chips for header meta lines (첫 몇 줄의 키:값)
  const kids = Array.from(root.children);
  const metaLines = [];
  for (const el of kids) {{
    if (el.tagName === "H1" || el.tagName === "HR") continue;
    if (el.tagName === "H2") break;
    if (el.tagName === "P" && /날짜|기록자|총 항목|신뢰도|기간|생성일|발행|모니터링|분석 항목/.test(el.textContent)) {{
      metaLines.push(el);
    }}
  }}
  if (metaLines.length) {{
    const box = document.createElement("div");
    box.className = "stats";
    metaLines.forEach(p => {{
      const chip = document.createElement("span");
      chip.className = "chip neutral";
      chip.textContent = p.textContent.trim();
      box.appendChild(chip);
      p.remove();
    }});
    const h1 = root.querySelector("h1");
    if (h1 && h1.nextSibling) root.insertBefore(box, h1.nextSibling);
    else root.prepend(box);
  }}
}}

qs("tab-daily").addEventListener("click", () => setTab("daily"));
qs("tab-monthly").addEventListener("click", () => setTab("monthly"));

(function init() {{
  const hash = (location.hash || "#daily").slice(1);
  const [k, ...rest] = hash.split("/");
  const startKind = (k === "monthly") ? "monthly" : "daily";
  setTab(startKind);
  const href = rest.length ? decodeURIComponent(rest.join("/")) : null;
  if (href) {{
    const item = (REPORTS[startKind] || []).find(x => x.href === href);
    loadReport(href, item ? item.title : href);
  }} else if ((REPORTS[startKind] || []).length) {{
    // auto-open latest
    const latest = REPORTS[startKind][0];
    loadReport(latest.href, latest.title);
  }}
}})();
</script>
</body>
</html>
"""

_REPORT_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin/>
<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" rel="stylesheet"/>
<style>{css}
body {{ background: var(--surface); }}
.standalone {{ max-width: 960px; margin: 0 auto; padding: 1.25rem 1.5rem 2.5rem; }}
</style>
</head>
<body>
<div class="standalone">
  <p class="back-link"><a href="../index.html#{kind}">← {kind_label} 목록</a></p>
  <div class="report">{content}</div>
</div>
</body>
</html>
"""


def _md_to_html(md_text: str) -> str:
    return markdown.markdown(md_text, extensions=_MD_EXT)


def _daily_meta(md_text: str) -> str:
    m = re.search(r"총 항목 수:\s*([^\n]+)", md_text)
    if m:
        # shorten e.g. "1건 (기사 1 / 논문 0) · ..."
        raw = m.group(1).strip()
        short = raw.split("·")[0].strip()
        return short
    return ""


def _monthly_meta(md_text: str) -> str:
    m = re.search(r"분석 항목:\s*([^\n]+)", md_text)
    if m:
        return m.group(1).split("·")[0].strip()
    return ""


def _write_report(rel_path: Path, title: str, kind: str, content: str) -> None:
    kind_label = "Daily" if kind == "daily" else "Monthly"
    html = _REPORT_HTML.format(
        title=title,
        css=_CSS,
        kind=kind,
        kind_label=kind_label,
        content=content,
    )
    out = SITE_DIR / rel_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def main() -> None:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    # Clean previous generated HTML (keep folder)
    for old in SITE_DIR.rglob("*.html"):
        old.unlink()

    catalog: dict[str, list[dict[str, str]]] = {"daily": [], "monthly": []}

    daily_files = sorted(DAILY_DIR.glob("daily_*.md"), reverse=True)
    for md_path in daily_files:
        iso = md_path.stem.replace("daily_", "")
        rel = Path("daily") / f"{iso}.html"
        md_text = md_path.read_text(encoding="utf-8")
        body = _md_to_html(md_text)
        title = f"Daily {iso}"
        _write_report(rel, title, "daily", body)
        catalog["daily"].append(
            {
                "label": iso,
                "title": title,
                "href": rel.as_posix(),
                "meta": _daily_meta(md_text),
            }
        )

    monthly_files = sorted(MONTHLY_DIR.glob("monthly_*.md"), reverse=True)
    for md_path in monthly_files:
        ym = md_path.stem.replace("monthly_", "")
        rel = Path("monthly") / f"{ym}.html"
        md_text = md_path.read_text(encoding="utf-8")
        body = _md_to_html(md_text)
        title = f"Monthly {ym}"
        _write_report(rel, title, "monthly", body)
        # Prefer Korean period label if present
        period = re.search(r"\*\*기간:\*\*\s*([^\n]+)", md_text)
        label = period.group(1).strip() if period else ym
        catalog["monthly"].append(
            {
                "label": label,
                "title": title,
                "href": rel.as_posix(),
                "meta": _monthly_meta(md_text),
            }
        )

    index = _INDEX_HTML.format(
        css=_CSS,
        reports_json=json.dumps(catalog, ensure_ascii=False),
    )
    (SITE_DIR / "index.html").write_text(index, encoding="utf-8")
    (SITE_DIR / "reports.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Backward-compatible stubs so old daily Pages URLs still resolve somewhat
    # if someone had bookmarked output/daily paths — not needed for new deploy root.

    print(
        f"Built site → {SITE_DIR.relative_to(ROOT)} "
        f"({len(catalog['daily'])} daily, {len(catalog['monthly'])} monthly)"
    )


if __name__ == "__main__":
    main()
