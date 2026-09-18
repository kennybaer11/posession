#!/bin/bash
# Hourly data run on the VPS - the server-side twin of .github/workflows/scrape.yml
# minus the odds scrape (run_odds.sh) and the GitHub Pages render. Cron calls it
# under flock, so a slow run is never overlapped by the next hour's.
cd /home/app/scraper || exit 1
. .venv/bin/activate
before=$(git rev-parse HEAD)
git pull -q --ff-only || echo "git pull failed - running on the checked-out code"
if [ "$(git rev-parse HEAD)" != "$before" ]; then
    # New code: this is the deploy. Packages first, then the web app, which
    # otherwise keeps serving the old version until it is restarted. The
    # restart is the one root action app may take - see deploy/sudoers.
    echo "== $(date '+%F %T') deploying $(git log --oneline -1)"
    if ! git diff --quiet "$before" HEAD -- requirements.txt; then
        pip install -q -r requirements.txt || echo "!! pip install failed"
    fi
    sudo -n /usr/bin/systemctl restart posession || echo "!! restart failed"
    # The cron entries and this script may have changed too.
    crontab deploy/crontab
fi

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
