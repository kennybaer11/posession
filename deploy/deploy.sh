#!/bin/bash
# Put new code from GitHub live. Cron runs this every minute, so a push is on
# posession.cz about a minute later; run_data.sh calls it too. Silent when
# there is nothing new - it only writes to the log when it deploys.
cd /home/app/scraper || exit 1
exec 9>/home/app/locks/deploy.lock
flock -n 9 || exit 0                       # a deploy is already running

git fetch -q origin main 2>/dev/null || exit 0   # GitHub unreachable: try next minute
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0

before=$(git rev-parse HEAD)
if ! git merge -q --ff-only origin/main; then
    echo "!! $(date '+%F %T') cannot fast-forward to origin/main - deploy skipped"
    exit 1
fi
echo "== $(date '+%F %T') deploying $(git log --oneline -1)"
# Packages first, then the web app, which otherwise keeps serving the old code
# until it is restarted. The restart is the one root action app may take -
# see deploy/sudoers.
if ! git diff --quiet "$before" HEAD -- requirements.txt; then
    .venv/bin/pip install -q -r requirements.txt || echo "!! pip install failed"
fi
sudo -n /usr/bin/systemctl restart posession || echo "!! restart failed"
crontab deploy/crontab                     # the schedule may have changed too
echo "== $(date '+%F %T') live"
