#!/bin/bash
# The cs2 project (github.com/kennybaer11/cs2): Counter-Strike 2 results from
# Liquipedia, Betano's round lines, the model's price on each, and settlement.
# betken.cz's E-sport pages read what it writes.
#
# Self-contained like run_aces.sh: the first run clones the repo and builds its
# venv, later runs pull and reinstall only when requirements.txt changes. The
# database is posession's own, so DATABASE_URL is read from this app's .env.
set -u
CS2=/home/app/cs2
echo "== $(date '+%F %T') cs2"

if [ ! -d "$CS2/.git" ]; then
    git clone -q https://github.com/kennybaer11/cs2.git "$CS2" || exit 1
else
    git -C "$CS2" pull -q --ff-only || echo "!! git pull failed - running the code already here"
fi
cd "$CS2" || exit 1

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv || exit 1
    rm -f .venv/.requirements
fi
if ! cmp -s requirements.txt .venv/.requirements; then
    .venv/bin/pip install -q -r requirements.txt && cp requirements.txt .venv/.requirements \
        || { echo "!! pip install failed"; exit 1; }
fi

DATABASE_URL="$(.venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values("/home/app/scraper/.env")["DATABASE_URL"])')" \
    || { echo "!! no DATABASE_URL in /home/app/scraper/.env"; exit 1; }
export DATABASE_URL

# Results first (only events still on or just finished are read; the very
# first run here reads every event since 2024, about half an hour, at
# Liquipedia's pace), then any new team names, then settle what has been played.
timeout 60m .venv/bin/python collect.py || echo "!! collect.py exited $?"
timeout 15m .venv/bin/python teams.py || echo "!! teams.py exited $?"
timeout 5m .venv/bin/python settle.py || echo "!! settle.py exited $?"

# Betano's round lines for matches still to start, and the model's price on
# each. A match's last price before kick-off is the one it settles with.
timeout 20m .venv/bin/python odds.py || echo "!! odds.py exited $?"
timeout 10m .venv/bin/python price.py --store --top 0 || echo "!! price.py exited $?"
echo "== $(date '+%F %T') done"
