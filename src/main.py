from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import click
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.catchup import run_daily_catchup
from src.config import PROJECT_ROOT, load_settings
from src.daily_sync import (
    realign_log_dates_from_published_at,
    refresh_all_daily_markdown,
    refilter_stored_range,
    repair_inconsistencies,
    reprocess_range,
    scan_inconsistencies,
)
from src.monthly import run_monthly_report
from src.pipeline import run_daily_monitor
from src.plan_document import save_plan_summary_markdown, summarize_plan_pdf
from src.storage import DailyLogStore


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


@click.group()
def cli() -> None:
    """Tech Market Intelligence Monitor CLI."""


@cli.command("summarize-plan")
@click.option(
    "--file",
    "pdf_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Local government plan PDF (e.g. 국가표준기본계획)",
)
@click.option("--title", default=None, help="Override document title in the report")
@click.option(
    "--save-text",
    is_flag=True,
    default=False,
    help="Save full extracted plain text to output/plans/",
)
def summarize_plan_cmd(
    pdf_path: Path,
    title: str | None,
    save_text: bool,
) -> None:
    """Summarize a long government plan PDF (saved under output/plans/, not daily log)."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    article = summarize_plan_pdf(
        pdf_path,
        settings,
        title=title,
        save_text=save_text,
    )
    summary_path = save_plan_summary_markdown(pdf_path, article)

    result: dict = {
        "status": "summarized",
        "title": article.title,
        "url": article.url,
        "source": article.source_name,
        "summary_markdown": str(summary_path),
        "ko_one_liner": article.ko_one_liner,
        "summary": article.llm_summary,
        "ko_summary_steps": article.ko_summary_steps,
        "keyword_relevance": article.keyword_relevance,
        "key_trends": article.key_trends,
    }

    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@cli.command("daily-refresh")
def daily_refresh_cmd() -> None:
    """Realign DB dates to KST published_at and rebuild all daily markdown (no LLM)."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    store = DailyLogStore(settings.database_path)
    realigned = realign_log_dates_from_published_at(store)
    results = refresh_all_daily_markdown(store, settings)
    click.echo(
        json.dumps(
            {"status": "refreshed", "realigned": realigned, "results": results},
            indent=2,
        )
    )


@cli.command("daily-repair")
def daily_repair_cmd() -> None:
    """Fix md/DB mismatches (no re-fetch unless markdown exists without DB rows)."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    store = DailyLogStore(settings.database_path)
    issues = scan_inconsistencies(store)
    if not issues:
        click.echo(json.dumps({"status": "ok", "issues": [], "results": []}, indent=2))
        return

    results = repair_inconsistencies(settings=settings)
    click.echo(
        json.dumps(
            {"status": "repaired", "issues": issues, "results": results},
            indent=2,
        )
    )


@cli.command("daily-refilter")
@click.option("--from", "from_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--to", "to_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
def daily_refilter_cmd(from_date: datetime, to_date: datetime) -> None:
    """Re-apply collection filter to stored DB rows and rebuild markdown (no LLM)."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    start = from_date.date()
    end = to_date.date()
    results = refilter_stored_range(start, end, settings=settings)
    click.echo(json.dumps({"status": "refiltered", "results": results}, indent=2))


@cli.command("daily-reprocess")
@click.option("--from", "from_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--to", "to_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option(
    "--fresh",
    is_flag=True,
    default=False,
    help="Clear existing DB/markdown for each date before re-fetching.",
)
def daily_reprocess_cmd(from_date: datetime, to_date: datetime, fresh: bool) -> None:
    """Re-run the daily pipeline for a date range using current rules (LLM calls)."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    start = from_date.date()
    end = to_date.date()
    results = reprocess_range(start, end, settings=settings, fresh=fresh)
    click.echo(json.dumps({"status": "reprocessed", "results": results}, indent=2))


@cli.command("daily-catchup")
def daily_catchup_cmd() -> None:
    """Run daily pipeline for every missing report through today (KST)."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    results = run_daily_catchup(settings=settings)
    click.echo(json.dumps(results, indent=2))


@cli.command("daily")
@click.option("--date", "run_date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
def daily_cmd(run_date: datetime | None) -> None:
    """Run daily fetch -> filter -> summarize -> store pipeline."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    target_date = run_date.date() if run_date else date.today() - timedelta(days=1)
    result = run_daily_monitor(log_date=target_date, settings=settings)
    click.echo(json.dumps(result, indent=2))


@cli.command("monthly")
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
@click.option(
    "--no-cleanup",
    is_flag=True,
    default=False,
    help="Keep daily markdown files after report generation.",
)
def monthly_cmd(year: int | None, month: int | None, no_cleanup: bool) -> None:
    """Aggregate daily logs, generate a monthly Markdown report, and delete daily files."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    result = run_monthly_report(year=year, month=month, cleanup_daily=not no_cleanup)
    click.echo(json.dumps(result, indent=2))


@cli.command("show-config")
def show_config_cmd() -> None:
    """Print project paths and keywords.txt top-3 (verify local setup)."""
    settings = load_settings()
    click.echo(
        json.dumps(
            {
                "project_root": str(PROJECT_ROOT),
                "keywords_path": str(settings.keywords_path),
                "keywords_path_exists": settings.keywords_path.is_file(),
                "analysis_keywords_top3": settings.analysis_keywords,
                "keyword_count": len(settings.keyword_labels),
                "database_path": str(settings.database_path),
                "reports_output_dir": str(settings.reports_output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@cli.command("schedule")
@click.option("--daily-hour", default=8, show_default=True, help="Hour (local time) for daily run")
@click.option(
    "--monthly-day",
    default="last",
    show_default=True,
    help="Day of month for monthly report (or 'last')",
)
def schedule_cmd(daily_hour: int, monthly_day: str) -> None:
    """Run the monitor on a 24h daily schedule plus month-end reporting."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    scheduler = BlockingScheduler()

    def daily_job() -> None:
        results = run_daily_catchup(settings=settings)
        logging.getLogger(__name__).info("Daily catch-up complete: %s", results)

    def monthly_job() -> None:
        today = date.today()
        result = run_monthly_report(year=today.year, month=today.month, cleanup_daily=True)
        logging.getLogger(__name__).info("Monthly job complete: %s", result)

    scheduler.add_job(
        daily_job,
        IntervalTrigger(hours=24),
        id="daily_monitor",
        next_run_time=datetime.now().replace(hour=daily_hour, minute=0, second=0, microsecond=0),
    )

    if monthly_day == "last":
        scheduler.add_job(monthly_job, CronTrigger(day="last", hour=daily_hour + 1, minute=0))
    else:
        scheduler.add_job(
            monthly_job,
            CronTrigger(day=int(monthly_day), hour=daily_hour + 1, minute=0),
        )

    click.echo("Scheduler started. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        click.echo("Scheduler stopped.")
        sys.exit(0)


if __name__ == "__main__":
    cli()
