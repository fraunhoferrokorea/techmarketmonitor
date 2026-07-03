"""Korea R&D intelligence monthly Markdown report for Fraunhofer Korea Office."""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from src.config import PROJECT_ROOT, Settings
from src.daily_report import (
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
        "score": log.get("rd_match_score") or compute_rd_match_score(article),
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
{year}년 {month}월 국내 R&D 인텔리gence 항목 {len(entries)}건(적합도 {MONTHLY_RD_MIN_SCORE}점 이상)을 바탕으로 월간 보고서 JSON을 작성하세요.

모니터링 컨텍스트 키워드(상위 3): {kw_label}
- 각 항목의 relevance(직접/간접/약함), matched_keywords, keyword_relevance 필드를 기준으로 중요도를 판단함.
- executive_summary·context_highlights·opportunities는 **직접·간접** 관련 항목을 정부·R&D 신호와 함께 우선 배치함.
- 정부·공공기관 투자 주체(actor)는 유지하되, 전력·에너지·그리드 등 컨텍스트 키워드와 직접 연결된 항목을 상단에 둠.

규칙:
- 한국 국내 정부·기업 R&D 위탁·협력 기회만 다룸. 해외 시장·글로벌 벤더 분석 금지.
- 모든 문장 명사형 종결(-함/-임/-었음). -습니다/-합니다 금지.
- 소스에 없는 수치·기관명 추가 금지.
- keyword_relevance, proposable, fact, actor/purpose/pain/strategy, relevance 필드를 적극 활용.

입력 데이터:
{json.dumps(entries, ensure_ascii=False)}

JSON 스키마:
{{
  "executive_summary": "3-4문장. 컨텍스트 키워드 직접·간접 이슈 + 국내 전력·에너지·ICT R&D 투자 트렌드",
  "context_highlights": [
    {{"relevance": "직접|간접", "matched_keywords": "매칭 키워드", "summary": "핵심 이슈 1-2문장", "refs": [1]}}
  ],
  "opportunities": [
    {{"field": "분야명(HVDC/BESS/스마트그리드 등)", "summary": "정부·기업 움직임 요약", "priority": "컨텍스트|정부", "refs": [1,2]}}
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


def _build_markdown(
    year: int,
    month: int,
    rd_logs: list[dict],
    compact: list[dict],
    structured: dict,
    top_keywords: list[str],
) -> str:
    today = date.today().isoformat()
    kw_label = " · ".join(top_keywords) if top_keywords else "(미설정)"
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
        structured.get("executive_summary", ""),
        "",
        "## 2. 컨텍스트 중요도 상위",
        "",
    ]

    highlights = structured.get("context_highlights") or []
    if highlights:
        for item in highlights:
            rel = item.get("relevance", "")
            matched = item.get("matched_keywords", "")
            summary = item.get("summary", "")
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
                prop = (item.get("proposable") or "")[:50]
                matched = item.get("matched_keywords") or prop or "—"
                issue = (item.get("summary") or item["title"])[:160]
                lines.append(
                    f"- **[{item['relevance']}]** ({matched}) {issue}"
                )
        else:
            lines.append("- 당월 수집 항목 중 모니터링 키워드 **직접·간접** 관련 항목 없음.")
            weak_items = [c for c in compact if c.get("relevance") == "약함"]
            if weak_items:
                lines.append(
                    f"- 정부·R&D 타깃 {len(weak_items)}건은 §4 Action Plan·§5 스코어카드에 정리함."
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
            summary = opp.get("summary", "")
            priority = opp.get("priority", "")
            tag = f" [{priority}]" if priority else ""
            lines.append(f"- **{field}{tag}:** {summary}")
    else:
        lines.append("- (해당 없음)")

    lines += [
        "",
        "## 4. Action Plan (접촉 타겟)",
        "",
        "| 타겟 (부처/기업) | 제안 R&D 영역 | 접촉 논리 |",
        "|----------------|--------------|----------|",
    ]

    action_plan = structured.get("action_plan") or []
    if action_plan:
        for action in action_plan:
            lines.append(
                f"| {_escape_table_cell(action.get('target', ''))} "
                f"| {_escape_table_cell(action.get('rd_area', ''))} "
                f"| {_escape_table_cell(action.get('contact_angle', ''))} |"
            )
    else:
        lines.append("| — | — | — |")

    lines += [
        "",
        "## 5. 부록: 월간 R&D 스코어카드",
        "",
        "| 점수 | 관련도 | 날짜 | 투자 주체 | 핵심 이슈 | 출처 |",
        "|------|--------|------|----------|----------|------|",
    ]

    for item in compact:
        issue = (item["summary"] or item["title"])[:120]
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
            f"| {_escape_table_cell(issue)} "
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
        structured = _fallback_structure(compact, top_keywords)

    markdown = _build_markdown(year, month, rd_logs, compact, structured, top_keywords)

    output_dir = settings.reports_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"monthly_{year:04d}-{month:02d}.md"
    output_path.write_text(markdown, encoding="utf-8")
    logger.info("Generated R&D monthly report: %s", output_path)
    return output_path


def _fallback_structure(entries: list[dict], top_keywords: list[str]) -> dict:
    by_field: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        kw = e.get("proposable") or "기타"
        by_field[kw[:30]].append(e)

    context_highlights = [
        {
            "relevance": e.get("relevance", ""),
            "matched_keywords": e.get("matched_keywords", ""),
            "summary": (e.get("summary") or e.get("title", ""))[:200],
            "refs": [e["ref"]],
        }
        for e in entries
        if e.get("relevance") in ("직접", "간접")
    ][:8]

    opportunities = [
        {
            "field": field,
            "summary": f"{len(items)}건의 국내 R&D 신호 포착",
            "priority": "컨텍스트" if any(i.get("relevance") in ("직접", "간접") for i in items) else "정부",
            "refs": [i["ref"] for i in items[:3]],
        }
        for field, items in list(by_field.items())[:5]
    ]
    action_plan = [
        {
            "target": e.get("actor") or e.get("source", ""),
            "contact_angle": e.get("strategy") or e.get("purpose", ""),
            "rd_area": e.get("proposable") or e.get("pain", ""),
            "refs": [e["ref"]],
        }
        for e in entries[:8]
        if e.get("actor")
    ]
    kw_label = " · ".join(top_keywords) if top_keywords else "모니터링 키워드"
    return {
        "executive_summary": (
            f"당월 R&D 적합 {MONTHLY_RD_MIN_SCORE}점 이상 항목 {len(entries)}건이 수집됨. "
            f"{kw_label} 기준 직접·간접 관련 {len(context_highlights)}건과 "
            "정부·기업 투자 주체 니즈를 스코어카드·Action Plan에 정리함."
        ),
        "context_highlights": context_highlights,
        "opportunities": opportunities,
        "action_plan": action_plan,
    }
