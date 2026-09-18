#!/bin/bash
# Hourly data run on the VPS - the server-side twin of .github/workflows/scrape.yml
# minus the odds scrape (run_odds.sh) and the GitHub Pages render. Cron calls it
# under flock, so a slow run is never overlapped by the next hour's.
cd /home/app/scraper || exit 1
. .venv/bin/activate
git pull -q --ff-only || echo "git pull failed - running on the checked-out code"

step() {  # a failed step is logged and the run goes on, as continue-on-error did
    echo "== $(date '+%F %T') $*"
    timeout 30m "$@" || echo "!! $* exited $?"
}

step python main.py
step python scrape_league.py both
step python import_odds.py odds.txt --insert-only
step python calibration.py
# advice + Telegram share a lock with run_odds.sh, so the same new line is
# never announced twice by the two jobs finishing together.
flock /home/app/locks/announce.lock bash -c '
    python advice.py; python notify.py; python monitor.py'
echo "== $(date '+%F %T') done"
