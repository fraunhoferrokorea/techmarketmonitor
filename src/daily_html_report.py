from __future__ import annotations

import html
import json
import os
from collections import Counter
from datetime import date
from typing import Any

from pathlib import Path

from src.daily_report import (
    _DEFAULT_DASHBOARD_BASE,
    _build_item_slugs,
    _build_rd_daily_theme,
    _build_summary_lines,
    _credibility,
    _credibility_grade,
    _extract_fact_sentence,
    _infer_tags,
    _item_heading_text,
    _material_type,
    _sort_articles_by_relevance,
    classify_keyword_relevance,
    keyword_relevance_label,
)
from src.models import SummarizedArticle
from src.policy_priority import is_gov_target
from src.rd_targeting import (
    compute_rd_match_score,
    format_rd_link_point,
    parse_rd_fields,
)


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _score_color(score: int) -> str:
    return {
        5: "#059669",
        4: "#2563eb",
        3: "#d97706",
        2: "#6b7280",
        1: "#9ca3af",
    }.get(score, "#6b7280")


def _score_tier(score: int) -> str:
    if score >= 5:
        return "high"
    if score >= 3:
        return "mid"
    return "low"


def _chart_payload(
    articles: list[SummarizedArticle],
    top_keywords: list[str] | None = None,
) -> dict[str, Any]:
    cred = Counter(_credibility_grade(_credibility(a)) for a in articles)
    rd_scores = Counter(compute_rd_match_score(a, top_keywords) for a in articles)
    sources = Counter(a.source_name for a in articles).most_common(8)
    materials = Counter(_material_type(a) for a in articles)

    return {
        "credibility": {
            "labels": ["A", "B", "C"],
            "values": [cred.get("A", 0), cred.get("B", 0), cred.get("C", 0)],
            "colors": ["#059669", "#2563eb", "#d97706"],
        },
        "rd_scores": {
            "labels": ["1점", "2점", "3점", "4점", "5점"],
            "values": [rd_scores.get(i, 0) for i in range(1, 6)],
            "colors": ["#9ca3af", "#6b7280", "#d97706", "#2563eb", "#059669"],
        },
        "sources": {
            "labels": [s[0] for s in sources],
            "values": [s[1] for s in sources],
        },
        "materials": {
            "labels": list(materials.keys()),
            "values": list(materials.values()),
        },
    }


def _at_glance_highlights(
    opportunities: list[dict[str, Any]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Top N opportunities for the hero glance strip."""
    ranked = sorted(opportunities, key=lambda c: (-c["score"], c["title"].lower()))
    return ranked[:limit]


def _rd_opportunity_cards(
    articles: list[SummarizedArticle],
    top_keywords: list[str],
    slugs: dict[str, str],
) -> list[dict[str, Any]]:
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
        cards.append(
            {
                "score": score,
                "tier": _score_tier(score),
                "title": article.title,
                "url": article.url,
                "anchor": slugs.get(article.url, ""),
                "issue": issue,
                "target": fields.get("investment_actor") or "명시 없음",
                "link_point": format_rd_link_point(
                    article.rd_proposable_area,
                    fields.get("pain_point", ""),
                    fields.get("investment_purpose", ""),
                ),
                "fact": article.rd_fact_basis or article.url,
            }
        )
    return cards


def _rd_insight_items(
    articles: list[SummarizedArticle],
    top_keywords: list[str],
) -> list[dict[str, str]]:
    from src.rd_targeting import _display_rd_field, is_domestic_rd_target

    domestic: list[tuple[int, SummarizedArticle, dict[str, str]]] = []
    for article in articles:
        fields = parse_rd_fields(article.ko_summary_steps)
        actor = fields.get("investment_actor", "")
        if not is_domestic_rd_target(actor):
            continue
        domestic.append((compute_rd_match_score(article, top_keywords), article, fields))

    domestic.sort(key=lambda row: (-row[0], row[1].title.lower()))
    items: list[dict[str, str]] = []
    for score, article, fields in domestic[:5]:
        parts = [f"목적: {fields['investment_purpose']}"] if fields.get("investment_purpose") else []
        pain = fields.get("pain_point", "")
        if pain and "보류" not in pain and "부족" not in pain:
            parts.append(f"니즈: {pain}")
        strategy = fields.get("approach_strategy", "")
        if strategy and "보류" not in strategy:
            parts.append(f"접근: {_display_rd_field(strategy)}")
        items.append(
            {
                "score": str(score),
                "actor": fields.get("investment_actor", ""),
                "detail": " | ".join(parts),
                "title": article.title,
                "url": article.url,
            }
        )
    return items


def _item_records(
    articles: list[SummarizedArticle],
    log_date: date,
    top_keywords: list[str],
    slugs: dict[str, str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, article in enumerate(articles, start=1):
        score = compute_rd_match_score(article, top_keywords)
        relevance = classify_keyword_relevance(article, top_keywords)
        rd_fields = parse_rd_fields(article.ko_summary_steps)
        records.append(
            {
                "index": index,
                "heading": _item_heading_text(article, index),
                "anchor": slugs[article.url],
                "title": article.title,
                "url": article.url,
                "source": article.source_name,
                "material": _material_type(article),
                "published": (
                    article.published_at.strftime("%Y-%m-%d")
                    if article.published_at
                    else log_date.isoformat()
                ),
                "credibility": _credibility(article),
                "cred_grade": _credibility_grade(_credibility(article)),
                "tags": _infer_tags(article),
                "summary": _build_summary_lines(article, top_keywords),
                "rd_score": score,
                "relevance": keyword_relevance_label(relevance),
                "gov_target": is_gov_target(article),
                "matched_keywords": article.matched_keywords[:4],
                "rd_area": article.rd_proposable_area,
                "rd_fact": article.rd_fact_basis,
                "rd_fields": {
                    k: v
                    for k, v in {
                        "투자 주체": rd_fields.get("investment_actor", ""),
                        "투자 목적": rd_fields.get("investment_purpose", ""),
                        "위탁 연구 니즈": rd_fields.get("pain_point", ""),
                        "접근 전략": rd_fields.get("approach_strategy", ""),
                    }.items()
                    if v
                },
            }
        )
    return records


def refresh_daily_index_html(output_dir: Path) -> Path:
    """Write index.html listing all daily dashboard pages (GitHub Pages entry)."""
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
<p>프라운호퍼 한국 · GitHub Pages에서 인포그래픽으로 열람</p>
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
    """Build a self-contained HTML dashboard for the daily R&D intelligence log."""
    kws = top_keywords or []
    kw_header = " · ".join(kws[:3]) if kws else "(미설정)"
    author = recorder or os.getenv("DAILY_LOG_RECORDER", "Tech Market Monitor (auto)")
    sorted_articles = _sort_articles_by_relevance(articles, kws)
    slugs = _build_item_slugs(sorted_articles)

    paper_count = sum(1 for a in articles if _material_type(a) == "논문")
    article_count = len(articles) - paper_count
    cred_counts = Counter(_credibility_grade(_credibility(a)) for a in articles)
    high_rd = sum(1 for a in articles if compute_rd_match_score(a, kws) >= 4)
    theme = _build_rd_daily_theme(articles, kws)

    charts = _chart_payload(articles, kws)
    opportunities = _rd_opportunity_cards(sorted_articles, kws, slugs)
    insights = _rd_insight_items(sorted_articles, kws)
    items = _item_records(sorted_articles, log_date, kws, slugs)

    date_str = log_date.isoformat()
    from src.daily_report import daily_markdown_github_url

    md_link = daily_markdown_github_url(log_date)
    pages_index = f"{_DEFAULT_DASHBOARD_BASE.rstrip('/')}/"

    opp_high = [c for c in opportunities if c["tier"] == "high"]
    opp_mid = [c for c in opportunities if c["tier"] == "mid"]
    opp_low = [c for c in opportunities if c["tier"] == "low"]
    glance = _at_glance_highlights(opportunities)

    def _score_bar(score: int) -> str:
        pct = score * 20
        color = _score_color(score)
        return (
            f'<div class="score-bar" title="R&D 적합 {score}/5">'
            f'<div class="score-bar-fill" style="width:{pct}%;background:{color}"></div>'
            f'<span class="score-bar-label">{score}/5</span></div>'
        )

    def _who_why_what(card: dict[str, Any]) -> str:
        return f"""<div class="www-grid">
  <div class="www-cell who"><span class="www-icon">누가</span><p>{_esc(card['target'])}</p></div>
  <div class="www-cell why"><span class="www-icon">왜</span><p>{_esc(card['issue'][:140])}</p></div>
  <div class="www-cell what"><span class="www-icon">무엇을</span><p>{_esc(card['link_point'])}</p></div>
</div>"""

    def _glance_card(card: dict[str, Any], rank: int) -> str:
        return f"""<article class="glance-card tier-{card['tier']}">
  <div class="glance-rank">#{rank}</div>
  {_score_bar(card['score'])}
  <h3><a href="#{_esc(card['anchor'])}">{_esc(card['title'][:55])}</a></h3>
  {_who_why_what(card)}
  <p class="glance-fact"><strong>팩트</strong> {_esc(card['fact'][:100])}</p>
</article>"""

    glance_html = "".join(_glance_card(c, i + 1) for i, c in enumerate(glance))
    if not glance_html:
        glance_html = (
            '<p class="muted">당일 R&D 적합 2점 이상 항목 없음 — 배경 모니터링 위주</p>'
        )

    def _opp_column(cards: list[dict[str, Any]], label: str, css: str) -> str:
        if not cards:
            return f"""<div class="board-col board-col-empty">
  <div class="board-col-head {css}">{_esc(label)} <span>0</span></div>
  <p class="muted empty-col">해당 구간 항목 없음</p>
</div>"""
        inner = []
        for card in cards:
            inner.append(
                f"""<article class="opp-card {css}">
  <div class="opp-head">
    {_score_bar(card['score'])}
    <h3><a href="#{_esc(card['anchor'])}">{_esc(card['title'][:60])}</a></h3>
  </div>
  {_who_why_what(card)}
  <p class="opp-fact"><span class="fact-lbl">팩트 체크</span> {_esc(card['fact'][:120])}</p>
  <a class="ext-link" href="{_esc(card['url'])}" target="_blank" rel="noopener">원문 ↗</a>
</article>"""
            )
        return f"""<div class="board-col">
  <div class="board-col-head {css}">{_esc(label)} <span>{len(cards)}</span></div>
  {''.join(inner)}
</div>"""

    insight_html = ""
    if insights:
        for item in insights:
            insight_html += f"""<div class="insight-card">
  <span class="score-badge sm" style="background:{_score_color(int(item['score']))}">{_esc(item['score'])}/5</span>
  <div>
    <strong>{_esc(item['actor'])}</strong>
    <p>{_esc(item['detail'])}</p>
    <a href="{_esc(item['url'])}" target="_blank" rel="noopener">{_esc(item['title'][:50])} ↗</a>
  </div>
</div>"""
    else:
        insight_html = '<p class="muted">당일 수집 항목 중 국내 투자 주체가 명시된 팩트 기반 타겟은 없음.</p>'

    items_html = []
    for rec in items:
        tags = "".join(f'<span class="tag">{_esc(t)}</span>' for t in rec["tags"])
        summary = "".join(
            f'<li class="{"interp" if s.startswith("(해석)") else ""}">{_esc(s)}</li>'
            for s in rec["summary"]
        )
        rd_rows = ""
        if rec["rd_area"]:
            rd_rows += f"<div><dt>제안 R&D 영역</dt><dd>{_esc(rec['rd_area'])}</dd></div>"
        if rec["rd_fact"]:
            rd_rows += f"<div><dt>팩트 근거</dt><dd>{_esc(rec['rd_fact'])}</dd></div>"
        for label, val in rec["rd_fields"].items():
            rd_rows += f"<div><dt>{_esc(label)}</dt><dd>{_esc(val)}</dd></div>"

        badges = f"""<span class="badge cred-{rec['cred_grade'].lower()}">{_esc(rec['cred_grade'])}</span>
<span class="badge" style="background:{_score_color(rec['rd_score'])}">R&D {rec['rd_score']}/5</span>"""
        if rec["relevance"] != "없음":
            badges += f'<span class="badge rel">{_esc(rec["relevance"])}</span>'
        if rec["gov_target"]:
            badges += '<span class="badge gov">정부·R&D 타깃</span>'

        kw_note = ", ".join(rec["matched_keywords"]) if rec["matched_keywords"] else ""
        collapsed = rec["rd_score"] < 2
        card_class = "item-card item-collapsed" if collapsed else "item-card"

        items_html.append(
            f"""<article class="{card_class}" id="{_esc(rec['anchor'])}" data-score="{rec['rd_score']}" data-cred="{_esc(rec['cred_grade'])}">
  <header class="item-head">
    <div class="item-badges">{badges}</div>
    <h3><a href="{_esc(rec['url'])}" target="_blank" rel="noopener">{_esc(rec['title'])}</a></h3>
    <div class="item-meta">
      <span>{_esc(rec['material'])}</span>
      <span>{_esc(rec['source'])}</span>
      <span>{_esc(rec['published'])}</span>
    </div>
  </header>
  <details class="item-details"{' open' if not collapsed else ''}>
    <summary>{'상세 보기' if collapsed else '요약 · R&D 타겟팅'}</summary>
    <ul class="summary-list">{summary}</ul>
    <dl class="rd-block">{rd_rows}</dl>
    <footer class="item-foot">
      <div class="tags">{tags}</div>
      {f'<span class="kw-note">매칭: {_esc(kw_note)}</span>' if kw_note else ''}
    </footer>
  </details>
</article>"""
        )

    chart_json = json.dumps(charts, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>국내 R&D 인텔리전스 · {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg: #f4f6f9;
  --surface: #ffffff;
  --text: #1e293b;
  --muted: #64748b;
  --border: #e2e8f0;
  --accent: #1d4ed8;
  --accent-soft: #dbeafe;
  --shadow: 0 1px 3px rgba(15,23,42,.08), 0 4px 12px rgba(15,23,42,.04);
  --radius: 12px;
  --font: "Pretendard", "Noto Sans KR", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: var(--font); background: var(--bg); color: var(--text); line-height: 1.6; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.page {{ max-width: 1280px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }}

.hero {{
  background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 55%, #3b82f6 100%);
  color: #fff; border-radius: var(--radius); padding: 1.75rem 2rem;
  box-shadow: var(--shadow); margin-bottom: 1.5rem;
}}
.hero h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: .35rem; }}
.hero .sub {{ opacity: .9; font-size: .95rem; }}
.hero .meta {{ display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 1rem; font-size: .85rem; opacity: .85; }}
.hero a {{ color: #bfdbfe; }}

.quick-nav {{
  display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1.25rem;
  position: sticky; top: 0; z-index: 10; background: var(--bg);
  padding: .5rem 0; border-bottom: 1px solid var(--border);
}}
.quick-nav a {{
  font-size: .82rem; font-weight: 600; padding: .35rem .9rem;
  border-radius: 999px; background: var(--surface); border: 1px solid var(--border);
  color: var(--text); box-shadow: var(--shadow);
}}
.quick-nav a:hover {{ background: var(--accent-soft); border-color: #93c5fd; text-decoration: none; }}

.glance {{
  background: var(--surface); border-radius: var(--radius); padding: 1.25rem 1.35rem;
  box-shadow: var(--shadow); border: 1px solid var(--border); margin-bottom: 1.5rem;
}}
.glance > h2 {{ font-size: 1rem; margin-bottom: 1rem; color: var(--accent); }}
.glance-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
.glance-card {{
  border-radius: 10px; padding: 1rem; border-left: 4px solid var(--border);
  background: #f8fafc;
}}
.glance-card.tier-high {{ border-left-color: #059669; background: #ecfdf5; }}
.glance-card.tier-mid {{ border-left-color: #d97706; background: #fffbeb; }}
.glance-card.tier-low {{ border-left-color: #6b7280; }}
.glance-rank {{
  font-size: .72rem; font-weight: 700; color: var(--muted); margin-bottom: .35rem;
}}
.glance-card h3 {{ font-size: .92rem; margin: .5rem 0; line-height: 1.4; }}
.glance-fact {{ font-size: .78rem; color: var(--muted); margin-top: .5rem; }}

.score-bar {{
  position: relative; height: 6px; background: #e2e8f0; border-radius: 3px; margin-bottom: .4rem;
}}
.score-bar-fill {{ height: 100%; border-radius: 3px; transition: width .3s; }}
.score-bar-label {{
  position: absolute; right: 0; top: -1.1rem; font-size: .7rem; font-weight: 700; color: var(--muted);
}}

.www-grid {{
  display: grid; grid-template-columns: 1fr; gap: .45rem; margin: .6rem 0;
}}
@media (min-width: 480px) {{ .www-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
.www-cell {{
  background: rgba(255,255,255,.7); border-radius: 6px; padding: .5rem .6rem;
  border: 1px solid var(--border);
}}
.www-icon {{
  display: block; font-size: .68rem; font-weight: 800; letter-spacing: .02em;
  color: var(--accent); margin-bottom: .2rem;
}}
.www-cell p {{ font-size: .78rem; line-height: 1.35; color: var(--text); margin: 0; }}
.www-cell.who .www-icon {{ color: #7c3aed; }}
.www-cell.why .www-icon {{ color: #2563eb; }}
.www-cell.what .www-icon {{ color: #059669; }}

.opp-fact, .glance-fact {{ font-size: .78rem; }}
.fact-lbl {{ font-weight: 700; color: var(--text); margin-right: .25rem; }}
.empty-col {{ padding: 1rem; text-align: center; font-size: .85rem; }}
.board-col-empty {{ opacity: .85; }}

.item-details summary {{
  cursor: pointer; font-size: .8rem; font-weight: 600; color: var(--accent);
  padding: .4rem 0; list-style: none;
}}
.item-details summary::-webkit-details-marker {{ display: none; }}
.item-details summary::before {{ content: "▸ "; }}
.item-details[open] summary::before {{ content: "▾ "; }}
.item-collapsed .item-head {{ margin-bottom: 0; }}

.kpi-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: .75rem; margin-bottom: 1.5rem;
}}
.kpi {{
  background: var(--surface); border-radius: var(--radius); padding: 1rem 1.1rem;
  box-shadow: var(--shadow); border: 1px solid var(--border);
}}
.kpi .val {{ font-size: 1.75rem; font-weight: 700; color: var(--accent); line-height: 1.2; }}
.kpi .lbl {{ font-size: .78rem; color: var(--muted); margin-top: .2rem; }}

.charts-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1rem; margin-bottom: 1.5rem;
}}
.chart-card {{
  background: var(--surface); border-radius: var(--radius); padding: 1rem 1.1rem;
  box-shadow: var(--shadow); border: 1px solid var(--border);
}}
.chart-card h2 {{ font-size: .85rem; color: var(--muted); margin-bottom: .75rem; font-weight: 600; }}
.chart-wrap {{ position: relative; height: 200px; }}

.theme-banner {{
  background: var(--accent-soft); border: 1px solid #93c5fd; border-radius: var(--radius);
  padding: 1rem 1.25rem; margin-bottom: 1.5rem;
}}
.theme-banner .kw {{ font-weight: 600; color: var(--accent); margin-bottom: .35rem; }}
.theme-banner .flow {{ font-size: 1.05rem; font-weight: 600; }}

.section {{ margin-bottom: 2rem; }}
.section > h2 {{
  font-size: 1.1rem; margin-bottom: 1rem; padding-bottom: .4rem;
  border-bottom: 2px solid var(--accent); display: inline-block;
}}

.board {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem; align-items: start;
}}
.board-col-head {{
  font-weight: 700; font-size: .9rem; padding: .5rem .75rem; border-radius: 8px;
  margin-bottom: .75rem; display: flex; justify-content: space-between;
}}
.board-col-head.high {{ background: #d1fae5; color: #065f46; }}
.board-col-head.mid {{ background: #dbeafe; color: #1e40af; }}
.board-col-head.low {{ background: #f1f5f9; color: #475569; }}

.opp-card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 1rem; margin-bottom: .75rem; box-shadow: var(--shadow);
}}
.opp-head {{ display: flex; gap: .6rem; align-items: flex-start; margin-bottom: .5rem; }}
.opp-head h3 {{ font-size: .92rem; line-height: 1.4; }}
.opp-issue {{ font-size: .85rem; color: var(--muted); margin-bottom: .6rem; }}
.opp-meta {{ font-size: .8rem; }}
.opp-meta div {{ margin-bottom: .35rem; }}
.opp-meta dt {{ font-weight: 600; color: var(--text); display: inline; }}
.opp-meta dt::after {{ content: ": "; }}
.opp-meta dd {{ display: inline; color: var(--muted); }}
.ext-link {{ font-size: .78rem; display: inline-block; margin-top: .5rem; }}

.score-badge {{
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 2.4rem; height: 1.5rem; padding: 0 .4rem;
  border-radius: 6px; color: #fff; font-size: .75rem; font-weight: 700; flex-shrink: 0;
}}
.score-badge.sm {{ min-width: 2rem; height: 1.3rem; font-size: .7rem; }}

.insights {{ display: flex; flex-direction: column; gap: .6rem; }}
.insight-card {{
  display: flex; gap: .75rem; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: .85rem 1rem; box-shadow: var(--shadow);
}}
.insight-card p {{ font-size: .85rem; color: var(--muted); margin: .2rem 0; }}
.insight-card a {{ font-size: .8rem; }}

.filter-bar {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1rem; }}
.filter-btn {{
  border: 1px solid var(--border); background: var(--surface); border-radius: 999px;
  padding: .35rem .85rem; font-size: .8rem; cursor: pointer; color: var(--text);
}}
.filter-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

.items-grid {{ display: grid; gap: 1rem; }}
.item-card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 1.1rem 1.25rem; box-shadow: var(--shadow);
}}
.item-badges {{ display: flex; flex-wrap: wrap; gap: .35rem; margin-bottom: .5rem; }}
.badge {{
  font-size: .7rem; font-weight: 600; padding: .15rem .5rem; border-radius: 4px;
  background: #e2e8f0; color: #334155;
}}
.badge.cred-a {{ background: #d1fae5; color: #065f46; }}
.badge.cred-b {{ background: #dbeafe; color: #1e40af; }}
.badge.rel {{ background: #fef3c7; color: #92400e; }}
.badge.gov {{ background: #ede9fe; color: #5b21b6; }}
.item-head h3 {{ font-size: 1rem; margin-bottom: .4rem; line-height: 1.45; }}
.item-meta {{ display: flex; flex-wrap: wrap; gap: .75rem; font-size: .78rem; color: var(--muted); }}
.item-meta span::before {{ content: "·"; margin-right: .75rem; color: var(--border); }}
.item-meta span:first-child::before {{ content: none; margin: 0; }}

.summary-list {{ margin: .75rem 0; padding-left: 1.2rem; font-size: .88rem; }}
.summary-list li {{ margin-bottom: .3rem; }}
.summary-list li.interp {{ color: var(--muted); font-style: italic; }}

.rd-block {{ font-size: .82rem; margin: .5rem 0; }}
.rd-block div {{ margin-bottom: .25rem; }}
.rd-block dt {{ font-weight: 600; display: inline; }}
.rd-block dt::after {{ content: ": "; }}
.rd-block dd {{ display: inline; color: var(--muted); }}

.item-foot {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
  gap: .5rem; margin-top: .75rem; padding-top: .6rem; border-top: 1px solid var(--border); }}
.tags {{ display: flex; flex-wrap: wrap; gap: .3rem; }}
.tag {{ font-size: .72rem; background: #f1f5f9; color: #475569; padding: .1rem .45rem; border-radius: 4px; }}
.kw-note {{ font-size: .75rem; color: var(--muted); }}

.muted {{ color: var(--muted); font-size: .9rem; }}
.footer {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border);
  font-size: .78rem; color: var(--muted); }}
.footer h3 {{ font-size: .85rem; color: var(--text); margin-bottom: .5rem; }}
.footer ul {{ padding-left: 1.2rem; }}
.footer li {{ margin-bottom: .25rem; }}

@media (max-width: 640px) {{
  .hero {{ padding: 1.25rem; }}
  .hero h1 {{ font-size: 1.25rem; }}
  .chart-wrap {{ height: 180px; }}
}}
</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <h1>국내 R&D 인텔리전스 데일리</h1>
    <p class="sub">프라운호퍼 한국 · 인포그래픽 대시보드 (한눈에 핵심 스캔)</p>
    <div class="meta">
      <span>📅 {date_str}</span>
      <span>✍️ {_esc(author)}</span>
      <span>📄 <a href="{_esc(md_link)}">상세 원문 (Markdown)</a></span>
      <span>📋 <a href="{_esc(pages_index)}">전체 목록</a></span>
    </div>
  </header>

  <nav class="quick-nav" aria-label="섹션 이동">
    <a href="#glance">한눈에 보기</a>
    <a href="#board">기회 보드</a>
    <a href="#insights">타겟 시사점</a>
    <a href="#items">전체 항목</a>
  </nav>

  <section class="glance" id="glance">
    <h2>오늘의 핵심 — 누가 · 왜 · 무엇을</h2>
    <div class="glance-grid">{glance_html}</div>
  </section>

  <div class="kpi-grid">
    <div class="kpi"><div class="val">{len(articles)}</div><div class="lbl">총 수집 항목</div></div>
    <div class="kpi"><div class="val">{article_count}</div><div class="lbl">기사</div></div>
    <div class="kpi"><div class="val">{paper_count}</div><div class="lbl">논문</div></div>
    <div class="kpi"><div class="val">{high_rd}</div><div class="lbl">R&D 적합 4점+</div></div>
    <div class="kpi"><div class="val">{cred_counts.get('A', 0)}</div><div class="lbl">신뢰도 A</div></div>
    <div class="kpi"><div class="val">{cred_counts.get('B', 0)}</div><div class="lbl">신뢰도 B</div></div>
  </div>

  <div class="charts-grid">
    <div class="chart-card"><h2>신뢰도 분포</h2><div class="chart-wrap"><canvas id="credChart"></canvas></div></div>
    <div class="chart-card"><h2>R&D 적합도 분포</h2><div class="chart-wrap"><canvas id="rdChart"></canvas></div></div>
    <div class="chart-card"><h2>출처별 항목</h2><div class="chart-wrap"><canvas id="srcChart"></canvas></div></div>
    <div class="chart-card"><h2>자료유형</h2><div class="chart-wrap"><canvas id="matChart"></canvas></div></div>
  </div>

  <div class="theme-banner">
    <div class="kw">모니터링 키워드: {_esc(kw_header)}</div>
    <div class="flow">{_esc(theme)}</div>
    <p class="muted" style="margin-top:.4rem;font-size:.85rem">
      오늘 수집 {len(articles)}건 (R&D 적합 4점 이상 {high_rd}건)
    </p>
  </div>

  <section class="section" id="board">
    <h2>R&D 기회 스캔 보드</h2>
    <div class="board">
      {_opp_column(opp_high, "높음 (4–5점)", "high")}
      {_opp_column(opp_mid, "중간 (3점)", "mid")}
      {_opp_column(opp_low, "참고 (2점)", "low")}
    </div>
    {f'<p class="muted" style="margin-top:.75rem">이하 {len(articles) - len(opportunities)}건은 R&D 적합 1점 또는 국내 투자 신호 미약으로 보드에서 생략</p>' if len(articles) > len(opportunities) else ''}
  </section>

  <section class="section" id="insights">
    <h2>국내 R&D 타겟 시사점</h2>
    <div class="insights">{insight_html}</div>
  </section>

  <section class="section" id="items">
    <h2>항목 기록</h2>
    <div class="filter-bar">
      <button class="filter-btn" data-filter="all">전체 ({len(items)})</button>
      <button class="filter-btn active" data-filter="mid">R&D 2점+ ({sum(1 for i in items if i['rd_score'] >= 2)})</button>
      <button class="filter-btn" data-filter="high">R&D 4점+ ({sum(1 for i in items if i['rd_score'] >= 4)})</button>
      <button class="filter-btn" data-filter="cred-a">신뢰도 A ({sum(1 for i in items if i['cred_grade'] == 'A')})</button>
    </div>
    <div class="items-grid" id="itemsGrid">
      {''.join(items_html)}
    </div>
  </section>

  <footer class="footer">
    <h3>신뢰도 등급 기준</h3>
    <ul>
      <li><strong>A:</strong> 정부·공공기관 원문, 연합뉴스·뉴시스 1차 보도, 공공 R&D·정책기관, 국내 학술지</li>
      <li><strong>B:</strong> 국내 경제·IT 전문매체, 2차 인용, 기업·공기업 IR/보도자료</li>
      <li><strong>C:</strong> 익명 소스·미검증 콘텐츠 (자동 생성 시 미사용)</li>
    </ul>
  </footer>
</div>

<script>
const CHARTS = {chart_json};

function doughnut(id, data, colors) {{
  new Chart(document.getElementById(id), {{
    type: 'doughnut',
    data: {{ labels: data.labels, datasets: [{{ data: data.values, backgroundColor: colors || ['#059669','#2563eb','#d97706','#94a3b8'] }}] }},
    options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }} }} }}
  }});
}}

function barH(id, labels, values, color) {{
  new Chart(document.getElementById(id), {{
    type: 'bar',
    data: {{ labels, datasets: [{{ data: values, backgroundColor: color || '#2563eb', borderRadius: 4 }}] }},
    options: {{
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ x: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }}, y: {{ ticks: {{ font: {{ size: 10 }} }} }} }}
    }}
  }});
}}

function barV(id, labels, values, colors) {{
  new Chart(document.getElementById(id), {{
    type: 'bar',
    data: {{ labels, datasets: [{{ data: values, backgroundColor: colors, borderRadius: 4 }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ y: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }}, x: {{ ticks: {{ font: {{ size: 10 }} }} }} }}
    }}
  }});
}}

doughnut('credChart', CHARTS.credibility, CHARTS.credibility.colors);
barV('rdChart', CHARTS.rd_scores.labels, CHARTS.rd_scores.values, CHARTS.rd_scores.colors);
barH('srcChart', CHARTS.sources.labels, CHARTS.sources.values, '#3b82f6');
doughnut('matChart', CHARTS.materials);

document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const f = btn.dataset.filter;
    document.querySelectorAll('.item-card').forEach(card => {{
      const score = parseInt(card.dataset.score, 10);
      const cred = card.dataset.cred;
      let show = true;
      if (f === 'high') show = score >= 4;
      else if (f === 'mid') show = score >= 2;
      else if (f === 'cred-a') show = cred === 'A';
      card.style.display = show ? '' : 'none';
    }});
  }});
}});

// Default: show R&D 2점+ only
document.querySelector('[data-filter="mid"]')?.click();
</script>
</body>
</html>"""
