"""Korea R&D intelligence monthly Markdown report for Fraunhofer Korea Office."""
from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from src.config import PROJECT_ROOT, Settings
from src.daily_report import (
    _highlight_after_md_label,
    _highlight_keywords,
    format_monitoring_keyword_header,
    keyword_relevance_label,
    log_to_summarized_article,
    monthly_credibility_distribution,
)
from src.rd_targeting import (
    MONTHLY_RD_MIN_SCORE,
    classify_monthly_context_relevance,
    compute_rd_match_score,
    parse_rd_fields,
    prepare_logs_for_monthly_rd,
)

logger = logging.getLogger(__name__)

_THEME_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("전력·그리드", re.compile(r"전력|그리드|grid|송배전|BESS|에너지저장", re.I)),
    ("제조AI·스마트공장", re.compile(r"제조|AI|에이전트|스마트공장|파운데이션", re.I)),
    ("표준·인증·보안", re.compile(r"표준|KS|인증|드론|대드론", re.I)),
    ("바이오·그린", re.compile(r"바이오|산림|그린", re.I)),
)


def _compact_entry(log: dict, ref: int, top_keywords: list[str]) -> dict:
    article = log_to_summarized_article(log)
    fields = parse_rd_fields(article.ko_summary_steps)
    relevance = classify_monthly_context_relevance(article, top_keywords)
    return {
        "ref": ref,
        "date": log.get("log_date", ""),
        "title": log.get("title", ""),
        "url": log.get("url", ""),
        "source": log.get("source_name", ""),
        "score": compute_rd_match_score(article, top_keywords, monthly=True),
        "relevance": keyword_relevance_label(relevance),
        "matched_keywords": ", ".join(article.matched_keywords[:5]),
        "actor": fields.get("investment_actor", ""),
        "purpose": fields.get("investment_purpose", ""),
        "pain": fields.get("pain_point", ""),
        "strategy": fields.get("approach_strategy", ""),
        "proposable": article.rd_proposable_area,
        "fact": article.rd_fact_basis,
        "keyword_relevance": (article.keyword_relevance or "").strip(),
        "summary": article.ko_one_liner or article.llm_summary,
    }


def _synthesize_monthly_ko(
    year: int,
    month: int,
    entries: list[dict],
    top_keywords: list[str],
) -> dict:
    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    kw_label = " · ".join(top_keywords) if top_keywords else "(미설정)"
    prompt = f"""당신은 Fraunhofer 한국 사무소 R&D 전략가입니다.
{year}년 {month}월 국내 R&D 인텔리전스 항목 {len(entries)}건(적합도 {MONTHLY_RD_MIN_SCORE}점 이상)을 바탕으로 **4~5페이지 분량**의 월간 보고서 JSON을 작성하세요.

모니터링 컨텍스트 키워드(keywords.txt 전체): {kw_label}
- 각 항목의 relevance(직접/간접/약함), matched_keywords, keyword_relevance 필드를 기준으로 중요도를 판단함.
- executive_summary·context_highlights·opportunities는 **직접·간접** 관련 항목을 정부·R&D 신호와 함께 우선 배치함.
- 정부·공공기관 투자 주체(actor)는 유지하되, 전력·에너지·그리드 등 모니터링 키워드와 직접 연결된 항목을 상단에 둠.

규칙:
- 한국 국내 정부·기업 R&D 위탁·협력 기회만 다룸. 해외 시장·글로벌 벤더 분석 금지.
- 모든 문장 명사형 종결(-함/-임/-었음). -습니다/-합니다 금지.
- 한글 문장 안에 영어 단어를 섞지 말 것. 용어는 한글로 통일(예: 인텔리전스). Intelligence·인텔리gence 등 혼용 금지.
- 소스에 없는 수치·기관명 추가 금지.
- keyword_relevance, proposable, fact, actor/purpose/pain/strategy, relevance 필드를 적극 활용.
- opportunities.summary는 분야별 서두 1~2문장(건수·[정부]·[컨텍스트] 라벨 금지).
- opportunities.items는 항목마다 육하원칙 기반 2~4문장: 누가(주체)·언제(일자)·무엇(발표·사업)·왜(목적)·어떻게(협력·접근). 명사형 종결.

입력 데이터:
{json.dumps(entries, ensure_ascii=False)}

JSON 스키마:
{{
  "executive_summary": "5~7문장. 모니터링 키워드 직접·간접 이슈 + 국내 전력·에너지·ICT R&D 투자 트렌드 + 당월 정부·기업 핵심 수치",
  "context_highlights": [
    {{"relevance": "직접|간접", "matched_keywords": "매칭 키워드", "summary": "핵심 이슈 2~3문장", "refs": [1]}}
  ],
  "opportunities": [
    {{"field": "분야명(전력·그리드/제조AI/표준·인증 등)", "summary": "분야 공통 맥락 1~2문장", "items": ["육하원칙 기반 항목 서술", "..."], "refs": [1,2]}}
  ],
  "action_plan": [
    {{"target": "부처/기업명", "contact_angle": "접촉 논리", "rd_area": "제안 R&D", "refs": [1]}}
  ]
}}"""
    response = client.chat.completions.create(
        model=os.getenv("MODEL_NAME", "gemini-2.0-flash-lite"),
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "국내 R&D 타겟팅 월간 보고서 작성. JSON만 반환.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    raw = (response.choices[0].message.content or "{}").strip()
    return json.loads(raw)


def _escape_table_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _hl_kws_for_entry(item: dict, top_keywords: list[str]) -> list[str]:
    """Matched + analysis keywords for one monthly entry, longest-first."""
    matched = [
        part.strip()
        for part in (item.get("matched_keywords") or "").split(",")
        if part.strip()
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in matched + list(top_keywords or []):
        kw = (raw or "").strip()
        if not kw:
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(kw)
    ordered.sort(key=len, reverse=True)
    return ordered


def _mark_keyword_tokens(text: str, keywords: list[str]) -> str:
    """Wrap comma/·-separated keyword tokens that match *keywords*."""
    if not text or text == "—" or not keywords:
        return text
    known = {kw.lower(): kw for kw in keywords if kw}
    parts = re.split(r"(\s*[,·]\s*)", text)
    out: list[str] = []
    for part in parts:
        if re.fullmatch(r"\s*[,·]\s*", part or ""):
            out.append(part)
            continue
        token = (part or "").strip()
        if token.lower() in known:
            out.append(f"<mark>{token}</mark>")
        else:
            out.append(part)
    return "".join(out)


def _build_markdown(
    year: int,
    month: int,
    rd_logs: list[dict],
    compact: list[dict],
    structured: dict,
    top_keywords: list[str],
) -> str:
    today = date.today().isoformat()
    kws = top_keywords or []
    kw_label = format_monitoring_keyword_header(kws)
    exec_summary = _highlight_keywords(
        structured.get("executive_summary", "") or "", kws
    )
    lines: list[str] = [
        "# 국내 R&D 인텔리전스 월간 보고서",
        "",
        f"**기간:** {year}년 {month}월",
        f"**생성일:** {today}",
        "**발행:** Fraunhofer Institute Korea Office · Tech Market Intelligence Monitor",
        f"**모니터링 키워드:** {kw_label}",
        "",
        f"**분석 항목:** {len(rd_logs)}건 (R&D 적합 {MONTHLY_RD_MIN_SCORE}점 이상) · "
        f"{monthly_credibility_distribution(rd_logs)}",
        "",
        "## 1. Executive Summary",
        "",
        exec_summary,
        "",
        "## 2. 컨텍스트 중요도 상위",
        "",
    ]

    highlights = structured.get("context_highlights") or []
    if highlights:
        for item in highlights:
            rel = item.get("relevance", "")
            matched = _mark_keyword_tokens(
                item.get("matched_keywords", "") or "", kws
            )
            summary = _highlight_keywords(item.get("summary", "") or "", kws)
            prefix = f"**[{rel}]**" if rel else "**[—]**"
            if matched:
                prefix += f" ({matched})"
            lines.append(f"- {prefix} {summary}")
    else:
        _rel_order = {"직접": 0, "간접": 1}
        context_items = sorted(
            [c for c in compact if c.get("relevance") in ("직접", "간접")],
            key=lambda c: (_rel_order.get(c.get("relevance", ""), 9), -c.get("score", 0)),
        )
        if context_items:
            for item in context_items[:8]:
                hl = _hl_kws_for_entry(item, kws)
                prop = (item.get("proposable") or "")[:50]
                matched_raw = item.get("matched_keywords") or prop or "—"
                matched = (
                    _mark_keyword_tokens(matched_raw, hl)
                    if item.get("matched_keywords")
                    else _highlight_keywords(matched_raw, hl)
                )
                issue = _highlight_keywords(
                    (item.get("summary") or item["title"])[:160], hl
                )
                lines.append(
                    f"- **[{item['relevance']}]** ({matched}) {issue}"
                )
        else:
            lines.append("- 당월 수집 항목 중 모니터링 키워드 **직접·간접** 관련 항목 없음.")
            weak_items = [c for c in compact if c.get("relevance") == "약함"]
            if weak_items:
                lines.append(
                    f"- 정부·R&D 타깃 {len(weak_items)}건은 §5 Action Plan·§6 스코어카드에 정리함."
                )

    lines += [
        "",
        "## 3. Opportunities (분야별 R&D 기회)",
        "",
    ]

    opportunities = structured.get("opportunities") or []
    if opportunities:
        for opp in opportunities:
            field = opp.get("field", "기타")
            summary = _highlight_keywords(opp.get("summary", "") or "", kws)
            lines.append(f"- **{field}:** {summary}")
            for item_line in opp.get("items") or []:
                lines.append(f"  - {_highlight_keywords(item_line or '', kws)}")
    else:
        lines.append("- (해당 없음)")

    lines += [
        "",
        "## 4. 주요 R&D 타겟 상세",
        "",
    ]
    _rel_order_detail = {"직접": 0, "간접": 1, "약함": 2}
    detail_items = sorted(
        _dedupe_entries(compact),
        key=lambda c: (
            _rel_order_detail.get(c.get("relevance", ""), 9),
            -c.get("score", 0),
        ),
    )[:8]
    for item in detail_items:
        hl = _hl_kws_for_entry(item, kws)
        title = _highlight_keywords(
            (item.get("summary") or item["title"])[:140], hl
        )
        lines.append(f"### [{item['ref']}] {title}")
        lines.append("")
        detail_fields = [
            ("투자 주체", item.get("actor")),
            ("투자 목적", item.get("purpose")),
            ("위탁 연구 니즈", item.get("pain")),
            ("제안 R&D", item.get("proposable")),
            ("접근 전략", item.get("strategy")),
            ("팩트 근거", item.get("fact")),
        ]
        for label, value in detail_fields:
            if value:
                lines.append(
                    _highlight_after_md_label(f"- **{label}:** {value}", hl)
                )
        rel = item.get("relevance", "—")
        matched = _mark_keyword_tokens(
            item.get("matched_keywords") or "—", hl
        )
        lines.append(
            f"- **관련도:** {rel} · 매칭: {matched} · 적합도 {item['score']}/5"
        )
        if item.get("url"):
            lines.append(f"- **출처:** [{item.get('source') or '링크'}]({item['url']})")
        lines.append("")

    lines += [
        "## 5. Action Plan (접촉 타겟)",
        "",
        "| 타겟 (부처/기업) | 제안 R&D 영역 | 접촉 논리 |",
        "|----------------|--------------|----------|",
    ]

    action_plan = structured.get("action_plan") or []
    if action_plan:
        for action in action_plan:
            target = _escape_table_cell(action.get("target", ""))
            rd_area = _highlight_keywords(
                _escape_table_cell(action.get("rd_area", "")), kws
            )
            angle = _highlight_keywords(
                _escape_table_cell(action.get("contact_angle", "")), kws
            )
            lines.append(f"| {target} | {rd_area} | {angle} |")
    else:
        lines.append("| — | — | — |")

    lines += [
        "",
        "## 6. 부록: 월간 R&D 스코어카드",
        "",
        "| 점수 | 관련도 | 날짜 | 투자 주체 | 핵심 이슈 | 출처 |",
        "|------|--------|------|----------|----------|------|",
    ]

    for item in compact:
        hl = _hl_kws_for_entry(item, kws)
        issue = _highlight_keywords(
            _escape_table_cell((item["summary"] or item["title"])[:120]), hl
        )
        url = item["url"]
        source_label = item["source"] or url
        if url:
            source_cell = f"[{source_label}]({url})"
        else:
            source_cell = source_label
        lines.append(
            f"| {item['score']}/5 "
            f"| {item.get('relevance', '—')} "
            f"| {item['date']} "
            f"| {_escape_table_cell(item['actor'] or '—')} "
            f"| {issue} "
            f"| {source_cell} |"
        )

    lines.append("")
    return "\n".join(lines)


def generate_rd_monthly_report(
    year: int,
    month: int,
    logs: list[dict],
    settings: Settings,
) -> Path:
    """Generate Korea-only R&D intelligence monthly Markdown report."""
    top_keywords = settings.analysis_keywords
    rd_logs, excluded = prepare_logs_for_monthly_rd(logs, top_keywords=top_keywords)
    if excluded:
        logger.info(
            "Excluded %d log(s) below R&D score %d for %04d-%02d",
            excluded,
            MONTHLY_RD_MIN_SCORE,
            year,
            month,
        )
    if not rd_logs:
        raise ValueError(
            f"No entries with R&D match score >= {MONTHLY_RD_MIN_SCORE} for {year}-{month:02d}."
        )

    compact = [_compact_entry(log, i, top_keywords) for i, log in enumerate(rd_logs, start=1)]
    try:
        structured = _synthesize_monthly_ko(year, month, compact, top_keywords)
    except Exception as exc:
        logger.warning("LLM monthly synthesis failed (%s) — using template fallback", exc)
        structured = _fallback_structure(compact, top_keywords, year, month)

    markdown = _build_markdown(year, month, rd_logs, compact, structured, top_keywords)

    output_dir = settings.reports_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"monthly_{year:04d}-{month:02d}.md"
    output_path.write_text(markdown, encoding="utf-8")
    logger.info("Generated R&D monthly report: %s", output_path)
    return output_path


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in entries:
        key = (entry.get("url") or "").strip() or (
            f"{entry.get('date', '')}|{entry.get('title', '')}"
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _theme_for_entry(entry: dict) -> str:
    blob = " ".join(
        [
            entry.get("proposable") or "",
            entry.get("pain") or "",
            entry.get("purpose") or "",
            entry.get("summary") or "",
            entry.get("title") or "",
        ]
    )
    for label, pattern in _THEME_RULES:
        if pattern.search(blob):
            return label
    return "기타 정부·R&D"


def _group_by_theme(entries: list[dict]) -> list[tuple[str, list[dict]]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        buckets[_theme_for_entry(entry)].append(entry)

    order = ["전력·그리드", "제조AI·스마트공장", "표준·인증·보안", "바이오·그린", "기타 정부·R&D"]
    ranked: list[tuple[str, list[dict]]] = []
    for label in order:
        if label in buckets:
            ranked.append((label, buckets.pop(label)))
    for label, items in buckets.items():
        ranked.append((label, items))
    return ranked


def _noun_clause(text: str) -> str:
    """Return a noun-style clause without duplicating -임/-함 endings."""
    t = (text or "").strip().rstrip(".。 ")
    if not t:
        return ""
    if re.search(r"(임|함|됨|었음|았음|했음|음)$", t):
        return t
    return f"{t}임"


def _entry_narrative(entry: dict) -> str:
    """One opportunity item as 5W1H-based flowing prose."""
    actor = (entry.get("actor") or entry.get("source") or "국내 주체").strip()
    when = (entry.get("date") or "").strip()
    what = (entry.get("summary") or entry.get("title") or "").strip()
    why = (entry.get("purpose") or "").strip()
    pain = (entry.get("pain") or "").strip()
    how = (entry.get("strategy") or entry.get("proposable") or "").strip()
    fact = (entry.get("fact") or "").strip()
    rel = entry.get("relevance", "")

    when_phrase = f"{when}에 " if when else ""
    sentences: list[str] = []

    if what:
        sentences.append(f"**{actor}** — {when_phrase}{_noun_clause(what)}.")
    else:
        sentences.append(f"**{actor}** — {when_phrase}국내 R&D 신호가 포착됨.")

    if why:
        sentences.append(f"정책·투자 목적은 {_noun_clause(why)}.")
    if fact and fact not in what:
        sentences.append(f"근거로는 {_noun_clause(fact)}.")
    if pain and pain not in why:
        sentences.append(f"필요한 위탁 연구 영역은 {_noun_clause(pain)}.")
    if how:
        sentences.append(f"협력 접근은 {_noun_clause(how)}.")
    if rel in ("직접", "간접"):
        sentences.append(f"모니터링 키워드(전력·그리드)와 {rel} 연관됨.")

    return " ".join(sentences)


def _theme_intro(theme: str, items: list[dict], top_keywords: list[str]) -> str:
    """분야별 서두 1~2문장 — 건수 나열 대신 공통 맥락 설명."""
    kw_label = " · ".join(top_keywords) if top_keywords else "모니터링 키워드"
    actors = sorted({i.get("actor", "") for i in items if i.get("actor")})[:3]
    actor_text = ", ".join(actors) if actors else "국내 정부·공공기관"

    intros = {
        "전력·그리드": (
            f"당월 {actor_text} 등이 {kw_label}와 연계된 국가 R&D·정책 신호를 발표함. "
            "전력 인프라·지능형 계통·송배전 분야 위탁 연구·국제 공동연구 제안 여지가 있음."
        ),
        "제조AI·스마트공장": (
            f"당월 {actor_text} 등이 제조업 AI 대전환·에이전트 실증·데이터·모델 개발에 "
            "민·관 합동 투자와 과제를 병행 추진함. 제조 현장 실증·고난도 모델 개발 협력 수요가 큼."
        ),
        "표준·인증·보안": (
            f"당월 {actor_text} 등이 국가표준(KS) 제정·성능시험·인증 체계를 구축함. "
            "표준 개발·시험평가 방법론·인증 제도 설계 분야 위탁 R&D 기회가 있음."
        ),
        "바이오·그린": (
            f"당월 {actor_text} 등이 산림·그린바이오 기술 이전·공동연구·사업화를 추진함. "
            "기술 이전 실증·공동 연구 과제 제안이 가능함."
        ),
    }
    return intros.get(
        theme,
        f"당월 {actor_text} 등에서 국내 R&D·정책 관련 신호가 확인됨. Action Plan에 투자 주체·니즈를 반영함.",
    )


def _build_executive_summary_fallback(
    entries: list[dict],
    top_keywords: list[str],
    year: int,
    month: int,
) -> str:
    unique = _dedupe_entries(entries)
    direct = [e for e in unique if e.get("relevance") == "직접"]
    indirect = [e for e in unique if e.get("relevance") == "간접"]
    weak = [e for e in unique if e.get("relevance") == "약함"]
    kw_label = " · ".join(top_keywords) if top_keywords else "모니터링 키워드"
    themes = [label for label, _ in _group_by_theme(unique)]

    parts = [
        f"{year}년 {month}월 국내 R&D 인텔리전스 월간 집계에서 R&D 적합 {MONTHLY_RD_MIN_SCORE}점 이상 "
        f"{len(unique)}건(원본 {len(entries)}건)이 분석됨.",
        f"{kw_label} 기준 직접 {len(direct)}건·간접 {len(indirect)}건·약함 {len(weak)}건으로 "
        "모니터링 컨텍스트 중요도를 구분함.",
    ]
    if direct:
        top = direct[0]
        parts.append(
            f"최우선 이슈는 **{top.get('actor') or '정부'}** — "
            f"{(top.get('summary') or top.get('title', ''))[:160]}."
        )
    if "제조AI·스마트공장" in themes:
        parts.append(
            "제조AI·스마트공장 축에서는 과기정통부·산업통상부·중기부가 "
            "20조원 규모 민·관 합동 투자와 에이전트 실증 사업을 병행 추진함."
        )
    if "표준·인증·보안" in themes:
        parts.append(
            "표준·인증 축에서는 산업통상부의 대드론 성능시험 국가표준(KS) 제정이 "
            "국가중요시설 보안 R&D 수요로 연결됨."
        )
    parts.append(
        "§2 컨텍스트 중요도·§3 분야별 기회·§4 타겟 상세·§5 Action Plan·§6 스코어카드에 "
        "투자 주체·니즈·접근 전략을 정리함."
    )
    return " ".join(parts)


def _fallback_structure(
    entries: list[dict],
    top_keywords: list[str],
    year: int,
    month: int,
) -> dict:
    unique = _dedupe_entries(entries)
    _rel_rank = {"직접": 0, "간접": 1, "약함": 2}

    context_highlights = sorted(
        [
            {
                "relevance": e.get("relevance", ""),
                "matched_keywords": e.get("matched_keywords", ""),
                "summary": (e.get("summary") or e.get("title", ""))[:280],
                "refs": [e["ref"]],
            }
            for e in unique
            if e.get("relevance") in ("직접", "간접")
        ],
        key=lambda h: (_rel_rank.get(h["relevance"], 9),),
    )[:8]

    opportunities = []
    for theme, items in _group_by_theme(unique):
        theme_items = sorted(
            items,
            key=lambda e: (_rel_rank.get(e.get("relevance", ""), 9), -e.get("score", 0)),
        )
        opportunities.append(
            {
                "field": theme,
                "summary": _theme_intro(theme, theme_items, top_keywords),
                "items": [_entry_narrative(e) for e in theme_items[:5]],
                "refs": [e["ref"] for e in theme_items[:5]],
            }
        )

    seen_actors: set[str] = set()
    action_plan = []
    for e in sorted(
        unique,
        key=lambda row: (_rel_rank.get(row.get("relevance", ""), 9), -row.get("score", 0)),
    ):
        actor = (e.get("actor") or "").strip()
        if not actor or actor in seen_actors:
            continue
        seen_actors.add(actor)
        action_plan.append(
            {
                "target": actor,
                "contact_angle": e.get("strategy") or e.get("purpose", ""),
                "rd_area": e.get("proposable") or e.get("pain", ""),
                "refs": [e["ref"]],
            }
        )
        if len(action_plan) >= 8:
            break

    return {
        "executive_summary": _build_executive_summary_fallback(
            entries, top_keywords, year, month
        ),
        "context_highlights": context_highlights,
        "opportunities": opportunities,
        "action_plan": action_plan,
    }
