"""Backfill ko_one_liner (5W1H executive-summary one-liner) for existing DB rows.

Usage:
    python backfill_ko_one_liner.py            # rows missing ko_one_liner
    python backfill_ko_one_liner.py --force    # regenerate all rows
    python backfill_ko_one_liner.py 2026-06-28 # one date only
"""
from __future__ import annotations

import json
import logging
import os
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
from src.daily_sync import rebuild_markdown_from_db
from src.storage import DailyLogStore
from src.summarizer import polish_korean, strip_cjk_from_korean

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_REQUEST_DELAY = 1.2

_KR_PROMPT = """\
아래 기사 요약을 바탕으로 데일리 Executive Summary 표에 들어갈 **한 줄 요약** 1문장을 작성하십시오.

[육하원칙 — 시장조사 담당자용]
기사에 있는 요소를 최대한 압축: (1)누가=주체·기관·인물 (2)어디=지역·시장 (3)무엇=사업·투자·제품·정책 (4)언제=일정·분기·년도 (5)왜/어떻게=동기·방식·규모.
수치($·GW·%·인원)·일정·지명·기업명 중 **3가지 이상** 반드시 포함. 70~150자.

[금지]
- "의문을 불러일으켰음", "중요성을 강조함", "관련성이 높음" 등 추상 표현
- "이 기사는", 지시대명사("이는", "이 프로젝트"만으로 시작) 단독 사용
- '-습니다', '-합니다', '-다' 종결

[문체]
명사형 종결(-었음/-함/-임/-전망됨). 한자·일본어 문자 금지.

기사 제목: {title}
출처: {source}
영문 요약:
{en_steps}
한국어 요약:
{ko_steps}

JSON 형식으로만 응답: {{"ko_one_liner": "<한 줄 요약>"}}
"""


def _generate_one_liner(client: OpenAI, model: str, row: sqlite3.Row) -> str:
    en_steps = json.loads(row["en_summary_steps"] or "[]")
    ko_steps = json.loads(row["ko_summary_steps"] or "[]")
    prompt = _KR_PROMPT.format(
        title=row["title"],
        source=row["source_name"],
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
            raw = (payload.get("ko_one_liner") or "").strip()
            return polish_korean(strip_cjk_from_korean(raw))
        except RateLimitError:
            if attempt == _MAX_RETRIES:
                raise
            wait = 2 ** attempt
            logger.warning("Rate limited — retrying in %ds", wait)
            time.sleep(wait)
    return ""


def backfill(target_date: date | None, settings, force: bool = False) -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    model = (os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL", "gemini-2.0-flash-lite")).strip()
    store = DailyLogStore(settings.database_path)

    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "ALTER TABLE daily_logs ADD COLUMN ko_one_liner TEXT NOT NULL DEFAULT ''"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass

    if target_date:
        query = (
            "SELECT * FROM daily_logs WHERE log_date = ? ORDER BY id ASC"
            if force
            else "SELECT * FROM daily_logs WHERE log_date = ? AND (ko_one_liner IS NULL OR ko_one_liner = '') ORDER BY id ASC"
        )
        rows = conn.execute(query, (target_date.isoformat(),)).fetchall()
    else:
        query = (
            "SELECT * FROM daily_logs ORDER BY log_date ASC, id ASC"
            if force
            else "SELECT * FROM daily_logs WHERE ko_one_liner IS NULL OR ko_one_liner = '' ORDER BY log_date ASC, id ASC"
        )
        rows = conn.execute(query).fetchall()

    if not rows:
        logger.info("모든 기사에 ko_one_liner가 이미 있습니다.")
        conn.close()
        return

    logger.info("%d건 처리 시작 (모델: %s)", len(rows), model)
    affected_dates: set[str] = set()

    for i, row in enumerate(rows, 1):
        logger.info("[%d/%d] %s", i, len(rows), row["title"][:60])
        try:
            one_liner = _generate_one_liner(client, model, row)
            if one_liner:
                conn.execute(
                    "UPDATE daily_logs SET ko_one_liner = ? WHERE id = ?",
                    (one_liner, row["id"]),
                )
                conn.commit()
                affected_dates.add(row["log_date"])
                logger.info("  → %s", one_liner[:80])
            else:
                logger.warning("  → LLM이 빈 값 반환")
        except Exception as exc:
            logger.error("  → 오류: %s", exc)

        if i < len(rows):
            time.sleep(_REQUEST_DELAY)

    conn.close()

    if affected_dates:
        logger.info("마크다운 재생성: %s", sorted(affected_dates))
        for d_str in sorted(affected_dates):
            rebuild_markdown_from_db(date.fromisoformat(d_str), store, settings)


def main() -> None:
    settings = load_settings()
    args = sys.argv[1:]
    force = "--force" in args
    date_args = [a for a in args if a != "--force"]
    target = date.fromisoformat(date_args[0]) if date_args else None
    backfill(target, settings, force=force)


if __name__ == "__main__":
    main()
