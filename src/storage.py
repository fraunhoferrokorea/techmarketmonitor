from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from src.models import SummarizedArticle


class DailyLogStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    source_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    published_at TEXT,
                    matched_keywords TEXT NOT NULL,
                    llm_summary TEXT NOT NULL,
                    key_trends TEXT NOT NULL,
                    ko_summary_steps TEXT NOT NULL DEFAULT '[]',
                    en_summary_steps TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_logs_log_date
                ON daily_logs(log_date)
                """
            )
            for column in ("ko_summary_steps", "en_summary_steps"):
                try:
                    conn.execute(
                        f"ALTER TABLE daily_logs ADD COLUMN {column} TEXT NOT NULL DEFAULT '[]'"
                    )
                except sqlite3.OperationalError:
                    pass  # Column already exists
            try:
                conn.execute(
                    "ALTER TABLE daily_logs ADD COLUMN keyword_relevance TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "ALTER TABLE daily_logs ADD COLUMN ko_one_liner TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass

    def update_korean_text(
        self,
        row_id: int,
        ko_summary_steps: list[str],
        keyword_relevance: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE daily_logs
                SET ko_summary_steps = ?, keyword_relevance = ?
                WHERE id = ?
                """,
                (
                    json.dumps(ko_summary_steps),
                    keyword_relevance,
                    row_id,
                ),
            )

    def save_entries(self, log_date: date, entries: list[SummarizedArticle]) -> int:
        inserted = 0
        now = datetime.utcnow().isoformat()

        with self._connect() as conn:
            for entry in entries:
                try:
                    conn.execute(
                        """
                        INSERT INTO daily_logs (
                            log_date, title, url, source_name, category,
                            published_at, matched_keywords, llm_summary,
                            key_trends, ko_summary_steps, en_summary_steps,
                            keyword_relevance, ko_one_liner, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            log_date.isoformat(),
                            entry.title,
                            entry.url,
                            entry.source_name,
                            entry.category,
                            entry.published_at.isoformat() if entry.published_at else None,
                            json.dumps(entry.matched_keywords),
                            entry.llm_summary,
                            json.dumps(entry.key_trends),
                            json.dumps(entry.ko_summary_steps),
                            json.dumps(entry.en_summary_steps),
                            entry.keyword_relevance,
                            entry.ko_one_liner,
                            now,
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    continue
        return inserted

    def get_logs_for_month(self, year: int, month: int) -> list[dict]:
        prefix = f"{year:04d}-{month:02d}"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM daily_logs
                WHERE log_date LIKE ?
                ORDER BY log_date ASC, id ASC
                """,
                (f"{prefix}-%",),
            ).fetchall()

        results: list[dict] = []
        for row in rows:
            item = dict(row)
            item["matched_keywords"] = json.loads(item["matched_keywords"])
            item["key_trends"] = json.loads(item["key_trends"])
            item["ko_summary_steps"] = json.loads(item.get("ko_summary_steps") or "[]")
            item["en_summary_steps"] = json.loads(item.get("en_summary_steps") or "[]")
            item["keyword_relevance"] = item.get("keyword_relevance") or ""
            item["ko_one_liner"] = item.get("ko_one_liner") or ""
            results.append(item)
        return results

    def get_seen_urls(self) -> set[str]:
        """Return all URLs that have already been stored (across all dates)."""
        with self._connect() as conn:
            rows = conn.execute("SELECT url FROM daily_logs").fetchall()
        return {row["url"] for row in rows}

    def count_for_date(self, log_date: date) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM daily_logs WHERE log_date = ?",
                (log_date.isoformat(),),
            ).fetchone()
        return int(row["count"]) if row else 0

    def get_log_dates(self) -> list[date]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT log_date FROM daily_logs ORDER BY log_date ASC"
            ).fetchall()
        return [date.fromisoformat(row["log_date"]) for row in rows]

    def get_entries_for_date(self, log_date: date) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM daily_logs
                WHERE log_date = ?
                ORDER BY id ASC
                """,
                (log_date.isoformat(),),
            ).fetchall()

        results: list[dict] = []
        for row in rows:
            item = dict(row)
            item["matched_keywords"] = json.loads(item["matched_keywords"])
            item["key_trends"] = json.loads(item["key_trends"])
            item["ko_summary_steps"] = json.loads(item.get("ko_summary_steps") or "[]")
            item["en_summary_steps"] = json.loads(item.get("en_summary_steps") or "[]")
            item["keyword_relevance"] = item.get("keyword_relevance") or ""
            item["ko_one_liner"] = item.get("ko_one_liner") or ""
            results.append(item)
        return results

    def delete_for_date(self, log_date: date) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM daily_logs WHERE log_date = ?",
                (log_date.isoformat(),),
            )
            return cursor.rowcount
