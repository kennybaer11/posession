#!/bin/bash
# Odds scrape on the VPS. No 45-minute step limit here, so on a slow
# webscraper.io day the run waits its job out instead of timing out and leaving
# the result to a later recovery. The 3-hour gap is enforced in the database,
# so this can run alongside the GitHub workflows without double spending.
cd /home/app/scraper || exit 1
. .venv/bin/activate
echo "== $(date '+%F %T') odds"
timeout 150m python odds_pipeline.py --hours 72 --skip-priced --write \
    --min-gap-hours 3 --wait-budget 120 || echo "!! odds_pipeline exited $?"
flock /home/app/locks/announce.lock bash -c 'python advice.py; python notify.py'
echo "== $(date '+%F %T') done"
