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

from src.config import PROJECT_ROOT, KeywordGroup, Settings, load_keyword_groups
from src.daily_report import (
    _highlight_after_md_label,
    _highlight_keywords,
    format_monitoring_keyword_header,
    format_source_display_name,
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
from src.press_evidence import (
    collect_press_evidence,
    fetch_press_corpus,
    format_evidence_basis,
    looks_like_keyword_dump,
    strip_unattested_monitoring_keywords,
    theme_intro_from_evidence,
)

logger = logging.getLogger(__name__)

OTHER_THEME = "기타 정부·R&D"
_KEYWORD_FOCUS_RELEVANCE = frozenset({"직접", "간접"})


def _apply_keyword_relevance_from_evidence(entries: list[dict]) -> None:
    """Upgrade relevance when monitoring keywords are attested in press corpus."""
    for entry in entries:
        attested = [k for k in (entry.get("attested_keywords") or []) if k]
        if not attested:
            continue
        # Press-attested monitoring terms are always keyword-focus (직접).
        entry["relevance"] = "직접"
        if not (entry.get("matched_keywords") or "").strip():
            entry["matched_keywords"] = ", ".join(attested[:5])


def _filter_keyword_focus_entries(
    entries: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split keyword-related (직접/간접) vs off-keyword (약함 등).

    Monthly §1–§5 use focus only. Off-keyword R&D noise is dropped from the
    narrative even if the Fraunhofer R&D score was high.
    """
    focus: list[dict] = []
    off: list[dict] = []
    for entry in entries:
        if entry.get("relevance") in _KEYWORD_FOCUS_RELEVANCE:
            focus.append(entry)
        else:
            off.append(entry)
    return focus, off


def _compact_entry(log: dict, ref: int, top_keywords: list[str]) -> dict:
    article = log_to_summarized_article(log)
    fields = parse_rd_fields(article.ko_summary_steps)
    relevance = classify_monthly_context_relevance(article, top_keywords)
    quotes = list(log.get("rd_evidence_quotes") or article.rd_evidence_quotes or [])
    return {
        "ref": ref,
        "date": log.get("log_date", ""),
        "title": log.get("title", ""),
        "url": log.get("url", ""),
        "source": format_source_display_name(log.get("source_name", "")),
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
        "evidence_quotes": quotes,
        "attested_keywords": [],
        "source_name_raw": log.get("source_name", ""),
    }


def _attach_press_evidence(entries: list[dict], top_keywords: list[str]) -> list[dict]:
    """Re-fetch government press text and attach attested keywords + verbatim quotes."""
    enriched: list[dict] = []
    for entry in entries:
        item = dict(entry)
        url = (item.get("url") or "").strip()
        corpus = ""
        if url:
            corpus = fetch_press_corpus(
                url,
                title=item.get("title") or "",
                source_name=item.get("source_name_raw") or item.get("source") or "",
            )
        if not corpus:
            # Fall back to already stored fact/summary text for non-gov or fetch misses.
            corpus = " ".join(
                part
                for part in (
                    item.get("title") or "",
                    item.get("fact") or "",
                    item.get("summary") or "",
                    " ".join(item.get("evidence_quotes") or []),
                )
                if part
            )
        evidence = collect_press_evidence(corpus, top_keywords)
        item["attested_keywords"] = evidence.attested_keywords
        if evidence.quotes:
            item["evidence_quotes"] = evidence.quotes
            item["fact"] = format_evidence_basis(evidence, fallback=item.get("fact") or "")
        elif item.get("evidence_quotes"):
            pass
        enriched.append(item)
        if evidence.attested_keywords:
            logger.info(
                "Press evidence ref=%s attested=%s quotes=%d",
                item.get("ref"),
                ",".join(evidence.attested_keywords[:6]),
                len(evidence.quotes),
            )
    return enriched


def _factcheck_structured(
    structured: dict,
    entries: list[dict],
    top_keywords: list[str],
    groups: tuple[KeywordGroup, ...] | list[KeywordGroup] | None = None,
) -> dict:
    """Strip keyword-dump hallucinations from LLM monthly synthesis."""
    by_ref = {e["ref"]: e for e in entries}
    all_attested: list[str] = []
    for e in entries:
        all_attested.extend(e.get("attested_keywords") or [])
    attested_set = list(dict.fromkeys(all_attested))

    exec_summary = structured.get("executive_summary") or ""
    # Always drop monitoring keywords not attested in press this month.
    exec_summary = strip_unattested_monitoring_keywords(
        exec_summary, top_keywords, attested_set
    )
    if looks_like_keyword_dump(exec_summary, top_keywords):
        exec_summary = strip_unattested_monitoring_keywords(
            exec_summary, top_keywords, attested_set
        )
    structured["executive_summary"] = _format_executive_summary_paragraphs(
        exec_summary
    )

    fixed_opps = []
    for opp in structured.get("opportunities") or []:
        field = opp.get("field") or OTHER_THEME
        summary = opp.get("summary") or ""
        theme_entries = [
            by_ref[r] for r in (opp.get("refs") or []) if r in by_ref
        ] or [e for e in entries if _theme_for_entry(e, groups) == field]
        theme_attested: list[str] = []
        for e in theme_entries:
            theme_attested.extend(e.get("attested_keywords") or [])
        theme_attested = list(dict.fromkeys(theme_attested))
        actors = sorted({e.get("actor", "") for e in theme_entries if e.get("actor")})
        if looks_like_keyword_dump(summary, top_keywords) or not summary.strip():
            summary = theme_intro_from_evidence(field, actors, theme_attested)
        else:
            summary = strip_unattested_monitoring_keywords(
                summary, top_keywords, theme_attested
            )
            if looks_like_keyword_dump(summary, top_keywords, min_hits=4):
                summary = theme_intro_from_evidence(field, actors, theme_attested)
        items = []
        for line in opp.get("items") or []:
            cleaned = strip_unattested_monitoring_keywords(
                line or "", top_keywords, theme_attested
            )
            if cleaned:
                items.append(cleaned)
        # Quotes belong in §4 detail; only append if no item already carries them.
        if theme_entries:
            existing = " ".join(items)
            for e in theme_entries:
                for quote in (e.get("evidence_quotes") or [])[:1]:
                    q = (quote or "").strip()
                    if q and q not in existing:
                        # Prefer attaching once via narrative rebuild, not raw dump.
                        break
        fixed_opps.append(
            {
                **opp,
                "summary": summary,
                "items": [
                    _normalize_opportunity_item_bold(x)
                    for x in _dedupe_opportunity_items(items or opp.get("items") or [])
                ],
            }
        )
    # Rebuild opportunities from keyword groups when LLM used legacy buckets.
    group_labels = {g.label for g in (groups or ())}
    legacy = {"제조AI·스마트공장", "표준·인증·보안", "바이오·그린", "전력·그리드"}
    used_fields = {o.get("field") for o in fixed_opps}
    if fixed_opps and (
        (used_fields & legacy) or (group_labels and not (used_fields & group_labels) and used_fields != {OTHER_THEME})
    ):
        # Prefer deterministic keyword-group buckets over stale LLM field names.
        rebuilt = []
        for theme, theme_items in _group_by_theme(entries, groups):
            theme_attested: list[str] = []
            for e in theme_items:
                theme_attested.extend(e.get("attested_keywords") or [])
            theme_attested = list(dict.fromkeys(theme_attested))
            actors = sorted({e.get("actor", "") for e in theme_items if e.get("actor")})
            rebuilt.append(
                {
                    "field": theme,
                    "summary": theme_intro_from_evidence(theme, actors, theme_attested),
                    "items": [
                        _normalize_opportunity_item_bold(_entry_narrative(e))
                        for e in theme_items[:5]
                    ],
                    "refs": [e["ref"] for e in theme_items[:5]],
                }
            )
        fixed_opps = rebuilt
    structured["opportunities"] = fixed_opps
    return structured


def _synthesize_monthly_ko(
    year: int,
    month: int,
    entries: list[dict],
    top_keywords: list[str],
    groups: tuple[KeywordGroup, ...] | list[KeywordGroup] | None = None,
) -> dict:
    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    kw_label = " · ".join(top_keywords) if top_keywords else "(미설정)"
    group_labels = [g.label for g in (groups or ())]
    field_choices = " / ".join(group_labels + [OTHER_THEME]) if group_labels else OTHER_THEME
    prompt = f"""당신은 Fraunhofer 한국 사무소 R&D 전략가입니다.
{year}년 {month}월 국내 R&D 인텔리전스 항목 {len(entries)}건(적합도 {MONTHLY_RD_MIN_SCORE}점 이상)을 바탕으로 **4~5페이지 분량**의 월간 보고서 JSON을 작성하세요.

모니터링 컨텍스트 키워드(keywords.txt 전체): {kw_label}
§3 분야(field) 허용값(keywords.txt 섹션 기준): {field_choices}
- opportunities.field는 위 허용값만 사용. 제조AI·스마트공장·표준·인증·바이오 등 레거시 라벨 금지.
- 각 항목의 relevance(직접/간접/약함), matched_keywords, keyword_relevance, **attested_keywords**, **evidence_quotes** 필드를 기준으로 중요도를 판단함.
- executive_summary·context_highlights·opportunities는 **직접·간접** 관련 항목을 정부·R&D 신호와 함께 우선 배치함.
- executive_summary는 주제가 바뀔 때마다 줄바꿈(문단 사이 빈 줄). 집계·관련도·최우선 이슈·분야축·후속 안내를 한 줄에 이어서 쓰지 말 것.
- **모니터링 축 = keywords.txt만.** executive_summary에 '제조AI·스마트공장 축', '표준·인증 축', '바이오 축' 등 레거시 고정 라벨을 쓰지 말 것. 키워드 미매칭 항목은 '관련도 약함 정부·R&D 신호'로만 언급.
- 정부·공공기관 투자 주체(actor)는 유지하되, 모니터링 키워드와 직접 연결된 항목을 상단에 둠.

규칙:
- 한국 국내 정부·기업 R&D 위탁·협력 기회만 다룸. 해외 시장·글로벌 벤더 분석 금지.
- 모든 문장 명사형 종결(-함/-임/-었음). -습니다/-합니다 금지.
- 한글 문장 안에 영어 단어를 섞지 말 것. 용어는 한글로 통일(예: 인텔리전스). Intelligence·인텔리gence 등 혼용 금지.

팩트체크 (필수):
1) **없는 내용 금지:** 입력 항목·evidence_quotes·fact에 없는 수치·기관명·사업명·기술용어를 추가하지 말 것. 모르면 생략.
2) **직접 인용 우선:** evidence_quotes가 있으면 항목 서술·summary·executive_summary에 「」 인용문을 원문 그대로 포함. 의역만으로 대체하지 말 것.
3) **의견 분리:** 추측·제안·시사점·'협력 가능'·'정책 정합' 등 분석 의견은 팩트 문장과 같은 줄에 쓰지 말 것. 의견이 꼭 필요할 때만 해당 문장 앞에 '(의견)'을 붙이고 줄바꿈으로 분리. 기본은 의견 생략(팩트만).

- **팩트체크 (키워드):** 모니터링 키워드 전체를 opportunities.summary에 나열하지 말 것. attested_keywords·evidence_quotes에 있는 용어만 언급.
- §4 상세는 **팩트만**: 일자·금액·건수·표준번호·사업명·장소·참석·시행일 등 fact/summary/evidence_quotes에 있는 구체 수치를 길게 서술.
- 위탁 연구 니즈·제안 R&D·접근 전략·관련도 문구를 opportunities에 쓰지 말 것(렌더러가 §4에서도 생략함).
- keyword_relevance, fact, actor, purpose, relevance, attested_keywords, evidence_quotes 필드를 적극 활용. pain/strategy/proposable는 참고만 하고 그대로 복사하지 말 것.
- opportunities.summary는 분야별 서두 1~2문장(건수·[정부]·[컨텍스트] 라벨 금지). **원문에 없는 키워드 리스트 삽입 금지.**
- opportunities.items는 항목마다 팩트 중심 1~2문장(짧게): 누가·언제·무엇·수치. **긴 「」 원문 인용은 §4에만.** 명사형 종결.
- **볼드 통일:** items는 `**투자주체** — 서술` 형식만. 분야명·금액·키워드를 볼드하지 말 것.
- **중복 금지:** 동일 정책·동일 금액(예: 20조원+100조원)이 복수 부처 보도로 나와도 opportunities에 한 번만. 투자 주체는 합쳐 표기.
- §3은 분야별 요약, §4는 상세 카드 — 같은 「」 인용·같은 문단을 양쪽에 복붙하지 말 것.

입력 데이터:
{json.dumps(entries, ensure_ascii=False)}

JSON 스키마:
{{
  "executive_summary": "5~7문장. 주제(집계 건수 / 관련도 구분 / 최우선 이슈 / 키워드 섹션 동향 / 후속 섹션 안내)가 바뀔 때마다 문단을 나누고 문단 사이에 빈 줄(\\n\\n)을 넣음. attested 키워드·원문 「」 인용 가능한 이슈만 + 당월 정부·기업 핵심 수치. 없는 사실 금지. 한 덩어리 문단으로 붙이지 말 것",
  "context_highlights": [
    {{"relevance": "직접|간접", "matched_keywords": "매칭 키워드", "summary": "핵심 이슈 2~3문장(팩트·수치·「」인용). 의견은 '(의견)' 별도 문장", "refs": [1]}}
  ],
  "opportunities": [
    {{"field": "{field_choices} 중 하나", "summary": "분야 공통 맥락 1~2문장(attested 키워드만)", "items": ["**주체** — 팩트 서술", "..."], "refs": [1,2]}}
  ],
  "action_plan": [
    {{"target": "부처/기업명", "contact_angle": "추진 팩트(일정·규모·시행일)", "rd_area": "핵심 팩트 요약(사업·표준·수치)", "refs": [1]}}
  ]
}}"""
    response = client.chat.completions.create(
        model=os.getenv("MODEL_NAME", "gemini-2.0-flash-lite"),
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "국내 R&D 타겟팅 월간 보고서 작성. JSON만 반환. "
                    "없는 내용 금지·원문 「」 직접 인용 우선·단순 의견은 '(의견)'으로 줄 바꿔 분리."
                ),
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
    *,
    off_keyword_excluded: int = 0,
) -> str:
    today = date.today().isoformat()
    kws = top_keywords or []
    kw_label = format_monitoring_keyword_header(kws)
    exec_summary = _highlight_keywords(
        _format_executive_summary_paragraphs(
            structured.get("executive_summary", "") or ""
        ),
        kws,
    )
    analysis_line = (
        f"**분석 항목:** 키워드 관련 {len(compact)}건 "
        f"(R&D 적합 {MONTHLY_RD_MIN_SCORE}점 이상 후보 {len(rd_logs)}건"
    )
    if off_keyword_excluded:
        analysis_line += f" · 키워드 무관 제외 {off_keyword_excluded}건"
    analysis_line += f") · {monthly_credibility_distribution(rd_logs)}"
    lines: list[str] = [
        "# 국내 R&D 인텔리전스 월간 보고서",
        "",
        f"**기간:** {year}년 {month}월",
        f"**생성일:** {today}",
        "**발행:** Fraunhofer Institute Korea Office · Tech Market Intelligence Monitor",
        f"**모니터링 키워드:** {kw_label}",
        "",
        analysis_line,
        "",
        "## 1. Executive Summary",
        "",
    ]
    if exec_summary:
        lines.extend(exec_summary.split("\n"))
    else:
        lines.append("")
    lines += [
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
                    f"- 정부·R&D 타깃 {len(weak_items)}건은 §6 스코어카드에 정리함."
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
            # §3 bold rule: theme plain; actor bold only (see _normalize_opportunity_item_bold).
            lines.append(f"- {field}: {summary}")
            for item_line in opp.get("items") or []:
                lines.append(
                    f"  - {_highlight_keywords(_normalize_opportunity_item_bold(item_line or ''), kws)}"
                )
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
        # Fact-only detail: omit speculative 위탁/제안/접근/관련도.
        fact_text = (item.get("fact") or item.get("summary") or "").strip()
        quotes = item.get("evidence_quotes") or []
        # Avoid repeating the same 「」 in 팩트 근거 and 원문 인용.
        if quotes and _QUOTE_RE.search(fact_text):
            stripped = _QUOTE_RE.sub("", fact_text)
            stripped = re.sub(r"원문 인용(?:\([^)]*\))?\s*:\s*", "", stripped)
            stripped = re.sub(r"\s{2,}", " ", stripped).strip(" .")
            fact_text = stripped or (item.get("summary") or "")
        detail_fields = [
            ("투자 주체", item.get("actor")),
            ("투자 목적", item.get("purpose")),
            ("팩트 근거", fact_text),
        ]
        for label, value in detail_fields:
            if value:
                lines.append(
                    _highlight_after_md_label(f"- **{label}:** {value}", hl)
                )
        if quotes:
            lines.append("- **원문 인용:**")
            for quote in quotes[:3]:
                lines.append(
                    _highlight_after_md_label(f"  - {quote}", hl)
                )
        attested = item.get("attested_keywords") or []
        if attested:
            lines.append(
                _highlight_after_md_label(
                    f"- **원문 확인 키워드:** {' · '.join(attested)}",
                    hl,
                )
            )
        if item.get("url"):
            links = [item["url"], *(item.get("alt_urls") or [])]
            labels = [
                s.strip()
                for s in re.split(r"\s*·\s*", item.get("source") or "링크")
                if s.strip()
            ]
            while len(labels) < len(links):
                labels.append(labels[-1] if labels else "링크")
            source_parts = [
                f"[{labels[i]}]({url})" for i, url in enumerate(links)
            ]
            lines.append(f"- **출처:** {' · '.join(source_parts)}")
        lines.append("")

    lines += [
        "## 5. Action Plan (접촉 타겟)",
        "",
        "| 타겟 (부처/기업) | 핵심 팩트 | 추진 팩트 |",
        "|----------------|----------|----------|",
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
        links = []
        if item.get("url"):
            links.append(item["url"])
        links.extend(item.get("alt_urls") or [])
        labels = [
            s.strip()
            for s in re.split(r"\s*·\s*", item.get("source") or "")
            if s.strip()
        ]
        if links:
            while len(labels) < len(links):
                labels.append(labels[-1] if labels else "링크")
            source_cell = " · ".join(
                f"[{labels[i]}]({url})" for i, url in enumerate(links)
            )
        else:
            source_cell = item.get("source") or "—"
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
    groups = _resolve_keyword_groups(settings, top_keywords)
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
    compact = _attach_press_evidence(compact, top_keywords)
    _apply_keyword_relevance_from_evidence(compact)
    source_count = len(compact)
    compact = _dedupe_entries(compact)
    # Re-number refs after policy-level merge.
    for i, entry in enumerate(compact, start=1):
        entry["ref"] = i
    if source_count != len(compact):
        logger.info(
            "Merged %d duplicate policy press releases → %d unique targets for %04d-%02d",
            source_count - len(compact),
            len(compact),
            year,
            month,
        )

    focus, off_keyword = _filter_keyword_focus_entries(compact)
    if off_keyword:
        logger.info(
            "Excluded %d off-keyword (약함) entr(y/ies) from monthly narrative for %04d-%02d",
            len(off_keyword),
            year,
            month,
        )
    if not focus:
        raise ValueError(
            f"No keyword-related (직접/간접) entries for {year}-{month:02d} "
            f"after press attestation against keywords.txt. "
            f"R&D-score candidates={len(rd_logs)}, off-keyword={len(off_keyword)}."
        )
    for i, entry in enumerate(focus, start=1):
        entry["ref"] = i
    compact = focus

    try:
        structured = _synthesize_monthly_ko(year, month, compact, top_keywords, groups)
    except Exception as exc:
        logger.warning("LLM monthly synthesis failed (%s) — using template fallback", exc)
        structured = _fallback_structure(compact, top_keywords, year, month, groups)
    structured = _factcheck_structured(structured, compact, top_keywords, groups)

    markdown = _build_markdown(
        year,
        month,
        rd_logs,
        compact,
        structured,
        top_keywords,
        off_keyword_excluded=len(off_keyword),
    )

    output_dir = settings.reports_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"monthly_{year:04d}-{month:02d}.md"
    output_path.write_text(markdown, encoding="utf-8")
    logger.info("Generated R&D monthly report: %s", output_path)
    return output_path


# Allow thousand separators (1,463억원) and optional 원
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:조|억|만)?원?|\d+(?:\.\d+)?(?:조|억|만)?원")
_QUOTE_RE = re.compile(r"「[^」]{12,}」")
# §3 item: bold only the investment actor before the first em dash.
_OPP_ACTOR_BOLD_RE = re.compile(
    r"^(?:\*\*)?(.+?)(?:\*\*)?\s*[—–-]\s*(.*)$",
    re.DOTALL,
)


def _normalize_opportunity_item_bold(text: str) -> str:
    """§3 bold convention: only the actor (주체) is bold; strip other **."""
    raw = (text or "").strip()
    if not raw:
        return raw
    m = _OPP_ACTOR_BOLD_RE.match(raw)
    if not m:
        # No actor separator — remove all bold so themes/phrases aren't emphasized.
        return re.sub(r"\*\*([^*]+)\*\*", r"\1", raw)
    actor = re.sub(r"\*\*", "", m.group(1)).strip()
    rest = re.sub(r"\*\*([^*]+)\*\*", r"\1", m.group(2)).strip()
    if not actor:
        return rest
    return f"**{actor}** — {rest}" if rest else f"**{actor}**"


def _policy_fingerprint(entry: dict) -> str:
    """Fingerprint same policy announced via multiple ministry press releases."""
    blob = " ".join(
        [
            entry.get("summary") or "",
            entry.get("fact") or "",
            entry.get("title") or "",
            entry.get("purpose") or "",
        ]
    )
    amounts = tuple(sorted(set(_AMOUNT_RE.findall(blob))))
    # Two+ distinctive money figures (e.g. 20조원+100조원) identify one policy
    # even when theme classifiers diverge across co-announcing ministries.
    if len(amounts) < 2:
        return ""
    return "|".join(amounts)


def _merge_deduped_entry(primary: dict, secondary: dict) -> dict:
    """Keep higher-score row; union actors/urls/quotes from the duplicate."""
    merged = dict(primary)
    actors = []
    for raw in (primary.get("actor"), secondary.get("actor")):
        for part in re.split(r"[,，·/]| 및 | 등", raw or ""):
            name = part.strip(" .")
            if name and name not in actors:
                actors.append(name)
    if actors:
        merged["actor"] = ", ".join(actors)
        if "등" not in merged["actor"] and len(actors) >= 2:
            merged["actor"] = f"{merged['actor']} 등"
    urls = []
    for item in (primary, secondary):
        u = (item.get("url") or "").strip()
        if u and u not in urls:
            urls.append(u)
    if urls:
        merged["url"] = urls[0]
        merged["alt_urls"] = urls[1:]
        sources = []
        for item in (primary, secondary):
            s = (item.get("source") or "").strip()
            if s and s not in sources:
                sources.append(s)
        if len(sources) > 1:
            merged["source"] = " · ".join(sources)
    quotes = list(primary.get("evidence_quotes") or [])
    for q in secondary.get("evidence_quotes") or []:
        if q and q not in quotes:
            quotes.append(q)
    merged["evidence_quotes"] = quotes
    fact = (primary.get("fact") or "").strip()
    sec_fact = (secondary.get("fact") or "").strip()
    if sec_fact and sec_fact not in fact:
        note = " (동일 정책·복수 부처 보도 통합)"
        merged["fact"] = (fact + note) if fact else sec_fact + note
    elif fact and "동일 정책" not in fact:
        merged["fact"] = f"{fact} (동일 정책·복수 부처 보도 통합)"
    if (secondary.get("score") or 0) > (primary.get("score") or 0):
        for key in ("summary", "title", "purpose", "relevance", "score"):
            if secondary.get(key):
                merged[key] = secondary[key]
    return merged


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    """Drop URL duplicates, then merge same-policy multi-ministry releases."""
    seen_url: set[str] = set()
    url_unique: list[dict] = []
    for entry in entries:
        key = (entry.get("url") or "").strip() or (
            f"{entry.get('date', '')}|{entry.get('title', '')}"
        )
        if key in seen_url:
            continue
        seen_url.add(key)
        url_unique.append(entry)

    unique: list[dict] = []
    fp_index: dict[str, int] = {}
    for entry in url_unique:
        fp = _policy_fingerprint(entry)
        if fp and fp in fp_index:
            idx = fp_index[fp]
            unique[idx] = _merge_deduped_entry(unique[idx], entry)
            continue
        if fp:
            fp_index[fp] = len(unique)
        unique.append(entry)
    return unique


def _dedupe_opportunity_items(items: list[str]) -> list[str]:
    """Collapse opportunity bullets that repeat the same policy amounts."""
    kept: list[str] = []
    seen_fps: set[str] = set()
    for line in items:
        text = (line or "").strip()
        if not text:
            continue
        amounts = tuple(sorted(set(_AMOUNT_RE.findall(text))))
        fp = "|".join(amounts) if len(amounts) >= 2 else ""
        if fp and fp in seen_fps:
            continue
        if fp:
            seen_fps.add(fp)
        # Keep only the first 「」 quote if the same text is repeated in-line.
        seen_quotes: set[str] = set()
        def _keep_first_quote(match: re.Match[str]) -> str:
            q = match.group(0)
            if q in seen_quotes:
                return ""
            seen_quotes.add(q)
            return q

        text = _QUOTE_RE.sub(_keep_first_quote, text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"(?:보도자료 원문:\s*)+$", "", text).strip(" .")
        if text:
            kept.append(text)
    return kept


def _theme_for_entry(
    entry: dict,
    groups: tuple[KeywordGroup, ...] | list[KeywordGroup] | None = None,
) -> str:
    """Assign §3 bucket from keywords.txt groups (not legacy hardcoded themes)."""
    groups = tuple(groups or ())
    if not groups:
        return OTHER_THEME

    attested = [k for k in (entry.get("attested_keywords") or []) if k]
    matched_raw = entry.get("matched_keywords") or ""
    matched = [p.strip() for p in re.split(r"[,，|/]", matched_raw) if p.strip()]
    blob = " ".join(
        [
            " ".join(attested),
            " ".join(matched),
            entry.get("summary") or "",
            entry.get("title") or "",
            entry.get("fact") or "",
            entry.get("purpose") or "",
            entry.get("proposable") or "",
            entry.get("pain") or "",
        ]
    ).lower()

    best_label = ""
    best_hits = 0
    for group in groups:
        hits = 0
        for kw in group.keywords:
            k = (kw or "").strip()
            if not k:
                continue
            # Prefer explicit attested/matched lists.
            if any(k.lower() == a.lower() for a in attested) or any(
                k.lower() == m.lower() for m in matched
            ):
                hits += 3
            elif k.lower() in blob:
                hits += 1
        if hits > best_hits:
            best_hits = hits
            best_label = group.label
    return best_label if best_hits > 0 else OTHER_THEME


def _group_by_theme(
    entries: list[dict],
    groups: tuple[KeywordGroup, ...] | list[KeywordGroup] | None = None,
) -> list[tuple[str, list[dict]]]:
    groups = tuple(groups or ())
    buckets: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        buckets[_theme_for_entry(entry, groups)].append(entry)

    order = [g.label for g in groups] + [OTHER_THEME]
    ranked: list[tuple[str, list[dict]]] = []
    for label in order:
        if label in buckets:
            ranked.append((label, buckets.pop(label)))
    for label, items in buckets.items():
        ranked.append((label, items))
    return ranked


def _resolve_keyword_groups(
    settings: Settings | None = None,
    top_keywords: list[str] | None = None,
) -> tuple[KeywordGroup, ...]:
    if settings and settings.keyword_groups:
        return settings.keyword_groups
    path = settings.keywords_path if settings else (PROJECT_ROOT / "keywords.txt")
    groups = load_keyword_groups(path)
    if groups:
        return groups
    kws = list(top_keywords or (settings.analysis_keywords if settings else []) or [])
    if kws:
        return (KeywordGroup(label="모니터링 키워드", keywords=tuple(kws)),)
    return ()


def _noun_clause(text: str) -> str:
    """Return a noun-style clause without duplicating -임/-함 endings."""
    t = (text or "").strip().rstrip(".。 ")
    if not t:
        return ""
    if re.search(r"(임|함|됨|었음|았음|했음|음)$", t):
        return t
    return f"{t}임"


def _entry_narrative(entry: dict) -> str:
    """Short §3 opportunity bullet — fact only; long quotes stay in §4."""
    actor = (entry.get("actor") or entry.get("source") or "국내 주체").strip()
    when = (entry.get("date") or "").strip()
    what = (entry.get("summary") or entry.get("title") or "").strip()
    fact = (entry.get("fact") or "").strip()
    rel = entry.get("relevance", "")

    when_phrase = f"{when}에 " if when else ""
    sentences: list[str] = []

    if what:
        sentences.append(f"**{actor}** — {when_phrase}{_noun_clause(what)}.")
    else:
        sentences.append(f"**{actor}** — {when_phrase}국내 R&D 신호가 포착됨.")

    # Keep §3 short: add a compact fact only when it adds numbers not already in what.
    if fact and fact not in what and not _QUOTE_RE.search(fact):
        amounts_in_what = set(_AMOUNT_RE.findall(what))
        amounts_in_fact = set(_AMOUNT_RE.findall(fact))
        if amounts_in_fact - amounts_in_what:
            compact = fact
            if len(compact) > 120:
                compact = compact[:117] + "…"
            sentences.append(_noun_clause(compact) + ".")
    attested = entry.get("attested_keywords") or []
    if attested and rel in ("직접", "간접"):
        sentences.append(
            f"원문 확인 키워드({' · '.join(attested[:3])})와 {rel} 연관됨."
        )

    return " ".join(sentences)


def _theme_intro(theme: str, items: list[dict], top_keywords: list[str]) -> str:
    """분야별 서두 — 원문에서 확인된(attested) 키워드만 언급."""
    del top_keywords  # monitoring list must not be pasted into the lead
    actors = sorted({i.get("actor", "") for i in items if i.get("actor")})
    attested: list[str] = []
    for item in items:
        attested.extend(item.get("attested_keywords") or [])
    attested = list(dict.fromkeys(attested))
    return theme_intro_from_evidence(theme, actors, attested)


def _format_executive_summary_paragraphs(text: str) -> str:
    """Split Executive Summary so each topic is its own paragraph."""
    text = (text or "").strip()
    if not text:
        return ""
    if "\n" in text:
        paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
        return "\n\n".join(paras)
    # Single block from LLM/fallback: one sentence per topic paragraph.
    parts = re.split(r"(?<=[.!?…])\s+", text)
    parts = [p.strip() for p in parts if p.strip()]
    return "\n\n".join(parts) if parts else text


def _build_executive_summary_fallback(
    entries: list[dict],
    top_keywords: list[str],
    year: int,
    month: int,
    groups: tuple[KeywordGroup, ...] | list[KeywordGroup] | None = None,
) -> str:
    unique = _dedupe_entries(entries)
    direct = [e for e in unique if e.get("relevance") == "직접"]
    indirect = [e for e in unique if e.get("relevance") == "간접"]
    attested: list[str] = []
    for e in unique:
        attested.extend(e.get("attested_keywords") or [])
    attested = list(dict.fromkeys(attested))
    kw_label = (
        " · ".join(attested[:10])
        if attested
        else (" · ".join(top_keywords[:5]) if top_keywords else "모니터링 키워드")
    )
    groups = tuple(groups or ())

    parts = [
        f"{year}년 {month}월 국내 R&D 인텔리전스 월간 집계에서 "
        f"keywords.txt 관련(직접·간접) {len(unique)}건을 분석함.",
        (
            f"보도자료 원문에서 확인된 키워드({kw_label}) 기준 "
            if attested
            else f"모니터링 키워드 기준 "
        )
        + f"직접 {len(direct)}건·간접 {len(indirect)}건임. "
        "키워드 무관(약함) 항목은 월간 본문에서 제외함.",
    ]
    if direct:
        top = direct[0]
        parts.append(
            f"최우선 이슈는 **{top.get('actor') or '정부'}** — "
            f"{(top.get('summary') or top.get('title', ''))[:160]}."
        )
    # keywords.txt sections only — off-keyword (약함) never enters this compact set.
    for label, items in _group_by_theme(unique, groups):
        if label == OTHER_THEME:
            continue
        focused = [
            e
            for e in items
            if e.get("relevance") in ("직접", "간접") or e.get("attested_keywords")
        ]
        if not focused:
            continue
        g0 = focused[0]
        parts.append(
            f"keywords.txt 섹션「{label}」에서는 "
            f"**{g0.get('actor') or '정부'}** 관련 "
            f"{(g0.get('summary') or g0.get('title') or '')[:140]}."
        )
    parts.append(
        "§2 컨텍스트 중요도·§3 분야별 기회·§4 타겟 상세·§5 Action Plan·§6 스코어카드에 "
        "키워드 관련 투자 주체·팩트 근거만 정리함."
    )
    return _format_executive_summary_paragraphs("\n\n".join(parts))


def _fallback_structure(
    entries: list[dict],
    top_keywords: list[str],
    year: int,
    month: int,
    groups: tuple[KeywordGroup, ...] | list[KeywordGroup] | None = None,
) -> dict:
    unique = _dedupe_entries(entries)
    groups = tuple(groups or ())
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
    for theme, items in _group_by_theme(unique, groups):
        if theme == OTHER_THEME:
            # Off-keyword buckets must not appear in §3 after focus filter.
            continue
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
        # Prefer non-quote fact summary for Action Plan cells.
        fact = (e.get("fact") or "").strip()
        if _QUOTE_RE.search(fact):
            fact = (e.get("summary") or e.get("purpose") or "")[:160]
        action_plan.append(
            {
                "target": actor,
                "contact_angle": fact or e.get("purpose", ""),
                "rd_area": (e.get("summary") or e.get("title") or "")[:160],
                "refs": [e["ref"]],
            }
        )
        if len(action_plan) >= 8:
            break

    return {
        "executive_summary": _build_executive_summary_fallback(
            entries, top_keywords, year, month, groups
        ),
        "context_highlights": context_highlights,
        "opportunities": opportunities,
        "action_plan": action_plan,
    }
