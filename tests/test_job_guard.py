"""Tests for scheduled-job locks and monthly LBD gating."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import run_monthly_if_last_bizday as monthly_gate
from src.job_guard import RunLock, is_lock_held


def test_run_lock_exclusive_and_release(tmp_path, monkeypatch):
    monkeypatch.setattr("src.job_guard._LOCK_DIR", tmp_path)

    first = RunLock("pipeline")
    assert first.acquire() is True
    assert is_lock_held("pipeline") is True

    second = RunLock("pipeline")
    assert second.acquire() is False

    first.release()
    assert is_lock_held("pipeline") is False
    assert second.acquire() is True
    second.release()


def test_stale_lock_taken_over(tmp_path, monkeypatch):
    monkeypatch.setattr("src.job_guard._LOCK_DIR", tmp_path)
    lock_path = tmp_path / "pipeline.lock"
    lock_path.write_text("999999 1.0\n", encoding="utf-8")  # dead pid, old stamp

    lock = RunLock("pipeline", stale_after_sec=10)
    assert lock.acquire() is True
    lock.release()


def test_monthly_gate_requires_yesterday_daily(tmp_path, monkeypatch):
    monkeypatch.setattr(monthly_gate, "_today_kst", lambda: date(2026, 7, 31))
    monkeypatch.setattr(
        monthly_gate,
        "_yesterday_daily_ready",
        lambda today: (False, "2026-07-30"),
    )

    monkeypatch.setattr("sys.argv", ["run_monthly_if_last_bizday.py"])
    try:
        monthly_gate.main()
        raised = None
    except SystemExit as exc:
        raised = exc.code
    assert raised == 0  # non-check-only: soft skip


def test_monthly_gate_check_only_fails_when_daily_missing(monkeypatch):
    monkeypatch.setattr(monthly_gate, "_today_kst", lambda: date(2026, 7, 31))
    monkeypatch.setattr(
        monthly_gate,
        "_yesterday_daily_ready",
        lambda today: (False, "2026-07-30"),
    )
    monkeypatch.setattr("sys.argv", ["run_monthly_if_last_bizday.py", "--check-only"])
    try:
        monthly_gate.main()
        raised = None
    except SystemExit as exc:
        raised = exc.code
    assert raised == 1


def test_monthly_gate_skips_when_report_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(monthly_gate, "_today_kst", lambda: date(2026, 7, 31))
    monkeypatch.setattr(
        monthly_gate,
        "_yesterday_daily_ready",
        lambda today: (True, "2026-07-30"),
    )
    report = tmp_path / "monthly_2026-07.md"
    report.write_text("# ok\n", encoding="utf-8")
    monkeypatch.setattr(
        "src.job_guard.monthly_report_path",
        lambda year, month: report,
    )
    monkeypatch.setattr("sys.argv", ["run_monthly_if_last_bizday.py"])
    try:
        monthly_gate.main()
        raised = None
    except SystemExit as exc:
        raised = exc.code
    assert raised in (0, None)
