#!/usr/bin/env python3
"""Entrypoint: run digest immediately or on a cron schedule.

Uses zone-aware scheduling so the digest runs at the configured local time
regardless of the container's system timezone. Wraps each pipeline run in
try/except so a crash never silently skips a day.
"""

import sys
import time
import logging
import traceback
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline import run_pipeline as run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("entrypoint")


def _parse_cron(cron_str: str) -> tuple[int, int]:
    """Extract hour and minute from a simple 5-field cron expression.

    Only supports the common ``minute hour * * *`` pattern (no day-of-week
    or month restrictions). Returns ``(hour, minute)``.
    """
    parts = cron_str.split()
    if len(parts) < 2:
        raise ValueError(f"Invalid cron expression: {cron_str!r}")
    minute = int(parts[0])
    hour = int(parts[1])
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        raise ValueError(f"Invalid cron time: hour={hour}, minute={minute}")
    return hour, minute


def _next_run_time(hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """Compute the next scheduled run time in the given timezone."""
    now = datetime.now(tz)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def main():
    if "--now" in sys.argv:
        log.info("Running digest immediately (--now flag)")
        try:
            run()
        except Exception:
            log.error("Pipeline failed:\n%s", traceback.format_exc())
            sys.exit(1)
        return

    # Load schedule from config
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    cron = config.get("schedule", {}).get("cron", "0 6 * * *")
    tz_name = config.get("schedule", {}).get("timezone", "UTC")
    tz = ZoneInfo(tz_name)

    hour, minute = _parse_cron(cron)
    run_time = f"{hour:02d}:{minute:02d}"
    log.info(f"Scheduling daily digest at {run_time} {tz_name}")

    last_run_date = None
    next_run = _next_run_time(hour, minute, tz)
    log.info(f"Next run: {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    while True:
        now = datetime.now(tz)
        today = now.date()

        # Check if it's time to run
        if now >= next_run and last_run_date != today:
            last_run_date = today
            try:
                log.info(f"Starting daily digest run at {now.strftime('%H:%M:%S %Z')}")
                run()
                log.info("Daily digest completed successfully")
            except Exception:
                log.error(
                    "Pipeline failed (will retry next scheduled window):\n%s",
                    traceback.format_exc(),
                )
                # Don't mark today as "done" so we retry if the scheduler loops again
                last_run_date = None

            # Schedule next run
            next_run = _next_run_time(hour, minute, tz)
            log.info(f"Next run: {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        # Sleep until the next check — use shorter intervals near the run time
        time_until_run = (next_run - now).total_seconds()
        if time_until_run < 60:
            sleep_for = 5  # Check every 5s in the last minute
        else:
            sleep_for = min(30, time_until_run - 60)  # Don't overshast the window
        time.sleep(max(1, sleep_for))


if __name__ == "__main__":
    main()
