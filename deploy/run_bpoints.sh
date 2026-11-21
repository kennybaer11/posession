#!/bin/bash
# The bpoints project (github.com/kennybaer11/bpoints): basketball results
# and DraftKings' lines from ESPN and the EuroLeague's API, the model's price
# on each Betano points line, the tips, and settlement. betken.cz's
# Basketball pages read what it writes.
#
# Self-contained like run_cs2.sh: the first run clones the repo and builds its
# venv, later runs pull and reinstall only when requirements.txt changes. The
# database is posession's own, so DATABASE_URL is read from this app's .env.
set -u
BP=/home/app/bpoints
echo "== $(date '+%F %T') bpoints"

if [ ! -d "$BP/.git" ]; then
    git clone -q https://github.com/kennybaer11/bpoints.git "$BP" || exit 1
else
    git -C "$BP" pull -q --ff-only || echo "!! git pull failed - running the code already here"
fi
cd "$BP" || exit 1

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv || exit 1
    rm -f .venv/.requirements
fi
if ! cmp -s requirements.txt .venv/.requirements; then
    .venv/bin/pip install -q -r requirements.txt && cp requirements.txt .venv/.requirements \
        || { echo "!! pip install failed"; exit 1; }
fi

env_value() {
    .venv/bin/python -c "from dotenv import dotenv_values; print(dotenv_values('/home/app/scraper/.env').get('$1') or '')"
}
DATABASE_URL="$(env_value DATABASE_URL)"
[ -n "$DATABASE_URL" ] || { echo "!! no DATABASE_URL in /home/app/scraper/.env"; exit 1; }
export DATABASE_URL

# Results of the last five days and the games of the next seven, with
# DraftKings' current line for each - the centre the lines are priced on.
timeout 30m .venv/bin/python collect.py || echo "!! collect.py exited $?"
timeout 5m .venv/bin/python settle.py || echo "!! settle.py exited $?"

# Betano's lines are NOT fetched here: Betano refuses this server (HTTP 403
# since at least 6 Nov 2026), so they come from the owner's PC (bpoints'
# betano_local.ps1), like the tennis and CS2 lines. This re-prices what is
# stored against the fresh DraftKings lines and rewrites the tips.
timeout 10m .venv/bin/python price.py --store --top 0 || echo "!! price.py exited $?"
timeout 5m .venv/bin/python advice.py || echo "!! advice.py exited $?"

TELEGRAM_BOT_TOKEN="$(env_value TELEGRAM_BOT_TOKEN)"
TELEGRAM_CHAT_ID="$(env_value TELEGRAM_CHAT_ID)"
export TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
timeout 5m .venv/bin/python notify.py || echo "!! notify.py exited $?"
echo "== $(date '+%F %T') done"
