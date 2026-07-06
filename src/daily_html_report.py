from __future__ import annotations

import html
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from src.daily_report import (
    _build_rd_daily_theme,
    _credibility,
    _credibility_grade,
    _extract_fact_sentence,
    _material_type,
    _sort_articles_by_relevance,
)
from src.models import SummarizedArticle
from src.rd_targeting import (
    compute_rd_match_score,
    format_rd_link_point,
    parse_rd_fields,
)


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _score_color(score: int) -> str:
    """Muted palette — only high scores get strong accent."""
    return {
        5: "#047857",
        4: "#1d4ed8",
        3: "#b45309",
        2: "#94a3b8",
        1: "#cbd5e1",
    }.get(score, "#94a3b8")


def _score_tier(score: int) -> str:
    if score >= 4:
        return "high"
    if score >= 3:
        return "mid"
    return "low"


def _stats_footer_text(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None,
    core_count: int,
) -> str:
    """One-line reference stats for the page footer."""
    kws = top_keywords or []
    cred = Counter(_credibility_grade(_credibility(a)) for a in articles)
    rd_scores = Counter(compute_rd_match_score(a, kws) for a in articles)
    sources = Counter(a.source_name for a in articles).most_common(5)
    materials = Counter(_material_type(a) for a in articles)
    paper_count = sum(1 for a in articles if _material_type(a) == "논문")
    high_rd = sum(1 for a in articles if compute_rd_match_score(a, kws) >= 4)

    rd_part = " · ".join(f"{i}점{rd_scores.get(i, 0)}" for i in range(1, 6))
    src_part = ", ".join(f"{name} {cnt}" for name, cnt in sources)
    mat_part = ", ".join(f"{label} {cnt}" for label, cnt in materials.items())

    return (
        f"수집 {len(articles)}건(기사 {len(articles) - paper_count}·논문 {paper_count})"
        f" · R&D 4점+ {high_rd} · 핵심 {core_count}"
        f" · 신뢰도 A {cred.get('A', 0)} / B {cred.get('B', 0)}"
        f" · 적합도 {rd_part}"
        f" · 출처 {src_part}"
        f" · 유형 {mat_part}"
    )


def _unified_rd_cards(
    articles: list[SummarizedArticle],
    top_keywords: list[str],
) -> list[dict[str, Any]]:
    """One deduplicated card per article (score >= 2) with WHO/WHY/WHAT + 접근."""
    ranked = sorted(
        articles,
        key=lambda a: (
            -compute_rd_match_score(a, top_keywords),
            a.title.lower(),
        ),
    )
    cards: list[dict[str, Any]] = []
    for article in ranked:
        score = compute_rd_match_score(article, top_keywords)
        if score < 2:
            continue
        fields = parse_rd_fields(article.ko_summary_steps)
        issue = (
            _extract_fact_sentence(article, top_keywords, "direct")
            or article.ko_one_liner
            or article.title
        )
        strategy = fields.get("approach_strategy", "")
        if strategy and ("보류" in strategy or strategy.strip() in ("정부=정책 정합", "해당 없음")):
            strategy = ""
        cards.append(
            {
                "score": score,
                "tier": _score_tier(score),
                "title": article.title,
                "url": article.url,
                "issue": issue,
                "target": fields.get("investment_actor") or "명시 없음",
                "link_point": format_rd_link_point(
                    article.rd_proposable_area,
                    fields.get("pain_point", ""),
                    fields.get("investment_purpose", ""),
                ),
                "fact": article.rd_fact_basis or "",
                "strategy": strategy,
            }
        )
    return cards


def refresh_daily_index_html(output_dir: Path) -> Path:
    """Write index.html listing all daily dashboard pages."""
    files = sorted(output_dir.glob("daily_*.html"), reverse=True)
    rows = []
    for path in files:
        if path.name == "index.html":
            continue
        date_part = path.stem.replace("daily_", "")
        rows.append(f'<li><a href="{_esc(path.name)}">{_esc(date_part)}</a></li>')
    body = "\n".join(rows) if rows else '<li class="muted">아직 생성된 데일리 대시보드가 없습니다.</li>'
    index_path = output_dir / "index.html"
    index_path.write_text(
        f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>국내 R&D 인텔리전스 데일리 대시보드</title>
<style>
body {{ font-family: "Pretendard", "Noto Sans KR", sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; color: #1e293b; }}
h1 {{ font-size: 1.25rem; color: #1d4ed8; }}
p {{ color: #64748b; font-size: .9rem; }}
ul {{ line-height: 2; padding-left: 1.2rem; }}
a {{ color: #1d4ed8; text-decoration: none; font-weight: 600; }}
a:hover {{ text-decoration: underline; }}
.muted {{ color: #94a3b8; }}
</style>
</head>
<body>
<h1>국내 R&D 인텔리전스 · 데일리 대시보드</h1>
<p>프라운호퍼 한국 · 인포그래픽 대시보드</p>
<ul>
{body}
</ul>
</body>
</html>""",
        encoding="utf-8",
    )
    return index_path


def build_daily_html(
    log_date: date,
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None = None,
    recorder: str | None = None,
) -> str:
    """Build a compact HTML dashboard: stats + unified R&D core cards only."""
    kws = top_keywords or []
    kw_header = " · ".join(kws[:3]) if kws else "(미설정)"
    author = recorder or os.getenv("DAILY_LOG_RECORDER", "Tech Market Monitor (auto)")
    sorted_articles = _sort_articles_by_relevance(articles, kws)

    theme = _build_rd_daily_theme(articles, kws)

    cards = _unified_rd_cards(sorted_articles, kws)
    stats_line = _stats_footer_text(articles, kws, len(cards))

    date_str = log_date.isoformat()
    from src.daily_report import daily_dashboard_public_url, daily_markdown_github_url

    md_link = daily_markdown_github_url(log_date)
    pages_index = daily_dashboard_public_url(log_date).rsplit("/", 1)[0] + "/index.html"

    by_tier: dict[str, list[dict[str, Any]]] = {"high": [], "mid": [], "low": []}
    for card in cards:
        by_tier[card["tier"]].append(card)

    def _score_badge(score: int) -> str:
        color = _score_color(score)
        emphasis = " score-emphasis" if score >= 4 else ""
        return (
            f'<span class="score-badge{emphasis}" style="--badge:{color}">{score}</span>'
        )

    def _core_card(card: dict[str, Any]) -> str:
        strategy_row = ""
        if card["strategy"]:
            strategy_row = f'<p class="card-meta">{_esc(card["strategy"])}</p>'
        fact_row = ""
        if card["fact"]:
            fact_row = f'<p class="card-fact">{_esc(card["fact"][:140])}</p>'
        return f"""<article class="core-card tier-{card['tier']}">
  <div class="card-top">
    {_score_badge(card['score'])}
    <h3><a href="{_esc(card['url'])}" target="_blank" rel="noopener">{_esc(card['title'][:72])}</a></h3>
  </div>
  <dl class="www-grid">
    <div class="www-row"><dt>누가</dt><dd>{_esc(card['target'])}</dd></div>
    <div class="www-row"><dt>왜</dt><dd>{_esc(card['issue'][:160])}</dd></div>
    <div class="www-row www-highlight"><dt>무엇을</dt><dd>{_esc(card['link_point'])}</dd></div>
  </dl>
  {strategy_row}
  {fact_row}
</article>"""

    def _tier_column(tier_cards: list[dict[str, Any]], label: str, css: str) -> str:
        if not tier_cards:
            return ""
        inner = "".join(_core_card(c) for c in tier_cards)
        return f"""<div class="board-col">
  <div class="board-col-head {css}">{_esc(label)}<span class="count">{len(tier_cards)}</span></div>
  {inner}
</div>"""

    board_html = (
        _tier_column(by_tier["high"], "높음 4–5점", "high")
        + _tier_column(by_tier["mid"], "중간 3점", "mid")
        + _tier_column(by_tier["low"], "참고 2점", "low")
    )
    if not cards:
        board_html = '<p class="muted">당일 R&D 적합 2점 이상 항목 없음 — 배경 모니터링 위주</p>'

    skipped = len(articles) - len(cards)
    skip_note = (
        f'<p class="skip-note">이하 {skipped}건은 R&D 적합 1점 또는 국내 투자 신호 미약으로 생략 · '
        f'<a href="{_esc(md_link)}">전체 항목은 Markdown 원문</a></p>'
        if skipped
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>국내 R&D 인텔리전스 · {date_str}</title>
<style>
:root {{
  --bg: #f1f5f9;
  --surface: #ffffff;
  --text: #0f172a;
  --text-secondary: #475569;
  --muted: #94a3b8;
  --border: #e2e8f0;
  --border-light: #f1f5f9;
  --accent: #1e40af;
  --accent-soft: #eff6ff;
  --radius: 10px;
  --font: "Pretendard", "Noto Sans KR", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: var(--font); background: var(--bg); color: var(--text); line-height: 1.55; font-size: 14px; -webkit-font-smoothing: antialiased; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.page {{ max-width: 1080px; margin: 0 auto; padding: 1.75rem 1.25rem 2.5rem; }}

/* ── Hero ── */
.hero {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem 1.75rem;
  margin-bottom: 1.5rem;
  border-left: 4px solid var(--accent);
}}
.hero-top {{ display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: .5rem; margin-bottom: .75rem; }}
.hero h1 {{ font-size: 1.15rem; font-weight: 700; color: var(--text); letter-spacing: -.02em; }}
.hero .date-tag {{ font-size: .75rem; font-weight: 600; color: var(--muted); background: var(--bg); padding: .2rem .55rem; border-radius: 4px; }}
.hero .theme {{ font-size: 1.05rem; font-weight: 600; color: var(--accent); line-height: 1.45; margin-bottom: .5rem; }}
.hero .kw {{ font-size: .8rem; color: var(--text-secondary); }}
.hero .meta {{ display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 1rem; padding-top: .75rem; border-top: 1px solid var(--border-light); font-size: .78rem; color: var(--muted); }}

/* ── Core section ── */
.core-section {{ margin-bottom: 1rem; }}
.core-section > h2 {{
  font-size: .72rem; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: .06em; margin-bottom: .85rem;
}}
.board {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.25rem; }}
.board-col-head {{
  font-size: .72rem; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: .05em;
  margin-bottom: .6rem; display: flex; justify-content: space-between; align-items: center;
}}
.board-col-head .count {{
  font-size: .7rem; font-weight: 600; color: var(--text-secondary);
  background: var(--bg); padding: .1rem .45rem; border-radius: 4px;
}}
.board-col-head.high .count {{ color: var(--accent); background: var(--accent-soft); }}

/* ── Cards ── */
.core-card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: .85rem 1rem; margin-bottom: .5rem;
}}
.core-card.tier-high {{ border-left: 3px solid #1d4ed8; }}
.core-card.tier-mid {{ border-left: 3px solid #cbd5e1; }}
.core-card.tier-low {{ border-left: 3px solid var(--border); }}

.card-top {{ display: flex; gap: .6rem; align-items: flex-start; margin-bottom: .65rem; }}
.score-badge {{
  flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center;
  width: 1.65rem; height: 1.65rem; border-radius: 6px;
  font-size: .75rem; font-weight: 700; color: #fff;
  background: var(--badge, var(--muted));
}}
.score-badge.score-emphasis {{ width: 1.85rem; height: 1.85rem; font-size: .82rem; box-shadow: 0 0 0 3px var(--accent-soft); }}
.core-card h3 {{ font-size: .88rem; font-weight: 600; line-height: 1.4; color: var(--text); }}
.core-card h3 a {{ color: inherit; }}
.core-card h3 a:hover {{ color: var(--accent); text-decoration: none; }}

.www-grid {{ display: flex; flex-direction: column; gap: .35rem; }}
.www-row {{ display: grid; grid-template-columns: 3.2rem 1fr; gap: .5rem; font-size: .8rem; }}
.www-row dt {{ color: var(--muted); font-weight: 600; font-size: .72rem; padding-top: .1rem; }}
.www-row dd {{ color: var(--text-secondary); line-height: 1.4; }}
.www-highlight dd {{ color: var(--text); font-weight: 500; }}

.card-meta {{ font-size: .76rem; color: var(--muted); margin-top: .5rem; padding-top: .45rem; border-top: 1px solid var(--border-light); }}
.card-fact {{ font-size: .74rem; color: var(--muted); margin-top: .3rem; }}

.skip-note {{ font-size: .76rem; color: var(--muted); margin-top: 1rem; }}
.muted {{ color: var(--muted); }}
.footer {{
  margin-top: 2rem; padding-top: .85rem; border-top: 1px solid var(--border);
  font-size: .65rem; color: var(--muted); line-height: 1.5;
}}
.footer .stats {{ margin-bottom: .35rem; }}

@media (max-width: 480px) {{
  .hero {{ padding: 1.1rem; }}
}}
</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <div class="hero-top">
      <h1>국내 R&D 인텔리전스</h1>
      <span class="date-tag">{date_str}</span>
    </div>
    <p class="theme">{_esc(theme)}</p>
    <p class="kw">{_esc(kw_header)}</p>
    <div class="meta">
      <span>{_esc(author)}</span>
      <a href="{_esc(md_link)}">상세 원문</a>
      <a href="{_esc(pages_index)}">날짜 목록</a>
    </div>
  </header>

  <section class="core-section" id="core">
    <h2>오늘의 R&D 핵심</h2>
    <div class="board">{board_html}</div>
    {skip_note}
  </section>

  <footer class="footer">
    <p class="stats">{_esc(stats_line)}</p>
    <p>신뢰도 A: 정부·공공 원문·1차 통신·공공 R&D기관 · B: 국내 전문매체·기업 IR</p>
  </footer>
</div>
</body>
</html>"""
