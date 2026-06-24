from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta

import click
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.catchup import run_daily_catchup
from src.config import load_settings
from src.monthly import run_monthly_report
from src.pipeline import run_daily_monitor


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


@click.group()
def cli() -> None:
    """Tech Market Intelligence Monitor CLI."""


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
    """Aggregate daily markdown reports, generate a monthly Word report, and delete daily files."""
    settings = load_settings()
    _configure_logging(settings.log_level)

    result = run_monthly_report(year=year, month=month, cleanup_daily=not no_cleanup)
    click.echo(json.dumps(result, indent=2))


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
