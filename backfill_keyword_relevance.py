"""Backfill keyword_relevance for existing DB rows that have an empty value.

Reads stored en/ko_summary_steps as article context, calls the LLM to generate
keyword_relevance, then updates the DB row and rebuilds all affected daily markdowns.

Usage:
    python backfill_keyword_relevance.py            # all dates missing relevance
    python backfill_keyword_relevance.py 2026-06-23 # specific date only
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

from src.config import load_settings
from src.daily_report import save_daily_report
from src.models import SummarizedArticle
from src.summarizer import polish_korean, strip_cjk_from_korean

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_REQUEST_DELAY = 1.2

_KR_PROMPT = """\
아래 기사가 분석 기준 키워드 상위 3개(이하 '추적 키워드')와 어떻게 구체적으로 연결되는지 한국어 1~3문단으로 서술하십시오.

[필수 규칙]
1. 첫 문장은 반드시 이 기사에 등장하는 고유명사·수치·날짜·이벤트명 중 하나로 시작할 것.
   다음 문장 유형은 절대 첫 문장으로 사용 금지:
   - "이 기사는 …", "이 논문은 …", "이 연구는 …"
   - "X 산업은 빠르게 발전하고 있다/발전함"
   - "X의 중요성을 강조한다/보여준다"
   - "(전력계통|파워그리드|스마트그리드)은/는 … 기술임/역할을 함"
   - "이 기사는 추적 키워드와 관련이 있음/관련성이 높음"

2. 올바른 첫 문장 예시 (참고용):
   - "SNEC 2026에서 나트륨이온 배터리와 장기 ESS가 전력망 핵심 자산으로 부상하면서…"
   - "오라클이 21,000명 감원으로 확보한 재원을 AI 데이터센터 인프라에 집중 투입함에 따라…"
   - "미국 전력망이 설비 용량의 절반만 가동 중이라는 IEEE Spectrum 분석에 따르면…"
   - "arXiv EESS.SY에 발표된 본 논문은 AI 훈련 전력 램프를 LLM 추론 유연성으로 상쇄하는…"

3. "관련이 있음", "관련성이 높음", "밀접한 관련이 있음" 등 내용 없는 일반론 금지.
4. 추적 키워드별로 문단을 나누거나 "~와 관련하여" 패턴 사용 금지 — 하나의 논리 흐름으로 통합 서술.
5. 이 기사가 추적 키워드와 실질적·구체적 연관이 전혀 없으면 빈 문자열("")로 반환.
6. 종결어미: 과거 '-었음/-았음/-했음/-났음/-켰음', 현재·일반 '-함/-임/-됨/-분석됨' 등 명사형. '-습니다', '-합니다', '-다' 종결 사용 금지.
7. 한자·일본어 문자 사용 금지. 반드시 한국어만.

추적 키워드 (상위 3개): {keywords}

기사 제목: {title}
출처: {source}
매칭 키워드: {matched}
영문 요약:
{en_steps}
한국어 요약:
{ko_steps}

JSON 형식으로만 응답: {{"keyword_relevance": "<한국어 1~3문단 또는 빈 문자열>"}}
"""


def _row_to_article(row: sqlite3.Row) -> SummarizedArticle:
    published_at = None
    if row["published_at"]:
        try:
            published_at = datetime.fromisoformat(row["published_at"])
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return SummarizedArticle(
        title=row["title"],
        url=row["url"],
        source_name=row["source_name"],
        category=row["category"],
        published_at=published_at,
        matched_keywords=json.loads(row["matched_keywords"] or "[]"),
        llm_summary=row["llm_summary"] or "",
        key_trends=json.loads(row["key_trends"] or "[]"),
        ko_summary_steps=json.loads(row["ko_summary_steps"] or "[]"),
        en_summary_steps=json.loads(row["en_summary_steps"] or "[]"),
        keyword_relevance=row["keyword_relevance"] or "" if "keyword_relevance" in row.keys() else "",
    )


def _generate_relevance(client: OpenAI, model: str, row: sqlite3.Row, top_keywords: list[str]) -> str:
    en_steps = json.loads(row["en_summary_steps"] or "[]")
    ko_steps = json.loads(row["ko_summary_steps"] or "[]")

    prompt = _KR_PROMPT.format(
        keywords=", ".join(top_keywords),
        title=row["title"],
        source=row["source_name"],
        matched=", ".join(json.loads(row["matched_keywords"] or "[]")),
        en_steps="\n".join(f"- {s}" for s in en_steps),
        ko_steps="\n".join(f"- {s}" for s in ko_steps),
    )

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            payload = json.loads(resp.choices[0].message.content or "{}")
            raw = (payload.get("keyword_relevance") or "").strip()
            return polish_korean(strip_cjk_from_korean(raw))
        except RateLimitError:
            if attempt == _MAX_RETRIES:
                raise
            wait = 2 ** attempt
            logger.warning("Rate limited — retrying in %ds", wait)
            time.sleep(wait)
    return ""


def backfill(target_date: date | None, settings, force: bool = False) -> None:
    import os
    load_dotenv(PROJECT_ROOT / ".env")

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    model = (os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL", "gemini-2.0-flash-lite")).strip()
    top_keywords = settings.keywords[:3]

    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    # Ensure column exists
    try:
        conn.execute("ALTER TABLE daily_logs ADD COLUMN keyword_relevance TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    if target_date:
        query = (
            "SELECT * FROM daily_logs WHERE log_date = ? ORDER BY id ASC"
            if force else
            "SELECT * FROM daily_logs WHERE log_date = ? AND (keyword_relevance IS NULL OR keyword_relevance = '') ORDER BY id ASC"
        )
        rows = conn.execute(query, (target_date.isoformat(),)).fetchall()
    else:
        query = (
            "SELECT * FROM daily_logs ORDER BY log_date ASC, id ASC"
            if force else
            "SELECT * FROM daily_logs WHERE keyword_relevance IS NULL OR keyword_relevance = '' ORDER BY log_date ASC, id ASC"
        )
        rows = conn.execute(query).fetchall()

    if not rows:
        logger.info("모든 기사에 keyword_relevance가 이미 있습니다.")
        conn.close()
        return

    logger.info("%d건 처리 시작 (모델: %s, 키워드: %s)", len(rows), model, top_keywords)
    affected_dates: set[str] = set()

    for i, row in enumerate(rows, 1):
        logger.info("[%d/%d] %s", i, len(rows), row["title"][:60])
        try:
            relevance = _generate_relevance(client, model, row, top_keywords)
            if relevance:
                conn.execute(
                    "UPDATE daily_logs SET keyword_relevance = ? WHERE id = ?",
                    (relevance, row["id"]),
                )
                conn.commit()
                affected_dates.add(row["log_date"])
                logger.info("  → 저장 완료 (%d자)", len(relevance))
            else:
                logger.warning("  → LLM이 빈 값 반환")
        except Exception as exc:
            logger.error("  → 오류: %s", exc)

        if i < len(rows):
            time.sleep(_REQUEST_DELAY)

    conn.close()

    # Rebuild affected daily markdowns
    if affected_dates:
        logger.info("\n마크다운 재생성: %s", sorted(affected_dates))
        from rebuild_daily_markdown import rebuild
        for d_str in sorted(affected_dates):
            rebuild(date.fromisoformat(d_str), settings)


def main() -> None:
    settings = load_settings()
    args = sys.argv[1:]
    force = "--force" in args
    date_args = [a for a in args if a != "--force"]
    target = date.fromisoformat(date_args[0]) if date_args else None
    backfill(target, settings, force=force)


if __name__ == "__main__":
    main()
