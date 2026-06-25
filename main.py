import argparse
import logging
import sys
from pathlib import Path

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    COLLECT_HOUR, COLLECT_MINUTE, BRIEFING_HOUR, BRIEFING_MINUTE,
    ALERT_INTERVAL_MINUTES, MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR, LOG_PATH,
)
from storage.db import init_db
from scheduler.jobs import collect_and_persist, run_morning_briefing, run_alert_check

MOROCCO_TZ = pytz.timezone("Africa/Casablanca")


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_dry_run() -> None:
    print("Running full pipeline in dry-run mode (no emails sent)...")
    run_morning_briefing(dry_run=True)
    run_alert_check(dry_run=True)
    print("\nDry run complete.")


def run_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=MOROCCO_TZ)

    scheduler.add_job(
        collect_and_persist,
        CronTrigger(hour=COLLECT_HOUR, minute=COLLECT_MINUTE, timezone=MOROCCO_TZ),
        id="collect",
        name="Collect all market data",
    )
    scheduler.add_job(
        run_morning_briefing,
        CronTrigger(hour=BRIEFING_HOUR, minute=BRIEFING_MINUTE, timezone=MOROCCO_TZ),
        id="briefing",
        name="Morning briefing email",
    )
    scheduler.add_job(
        run_alert_check,
        CronTrigger(
            hour=f"{MARKET_OPEN_HOUR}-{MARKET_CLOSE_HOUR}",
            minute=f"*/{ALERT_INTERVAL_MINUTES}",
            timezone=MOROCCO_TZ,
        ),
        id="alerts",
        name="Intraday alert check",
    )

    logging.getLogger(__name__).info("Scheduler started. Press Ctrl+C to exit.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mizan BVC AI Assistant")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline once without sending emails",
    )
    args = parser.parse_args()

    setup_logging()
    init_db()

    if args.dry_run:
        run_dry_run()
    else:
        run_scheduler()
