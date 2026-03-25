#!/usr/bin/env python3
"""Entrypoint: run digest immediately or on a cron schedule."""

import sys
import time
import logging
import schedule
import yaml
from pathlib import Path
from digest import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("entrypoint")


def main():
    if "--now" in sys.argv:
        log.info("Running digest immediately (--now flag)")
        run()
        return

    # Load schedule from config
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    cron = config.get("schedule", {}).get("cron", "0 6 * * *")
    
    # Parse simple HH:MM from cron (minute hour * * *)
    parts = cron.split()
    minute = parts[0].zfill(2)
    hour = parts[1].zfill(2)
    run_time = f"{hour}:{minute}"

    log.info(f"Scheduling daily digest at {run_time}")
    schedule.every().day.at(run_time).do(run)

    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
