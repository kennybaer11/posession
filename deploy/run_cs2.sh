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

# Betano's round lines are NOT fetched here: Betano refuses this server (HTTP
# 403 on every request since at least 6 Nov 2026), so they are collected from
# the owner's PC (cs2's betano_local.ps1), like the tennis Betano lines. This
# re-prices what is stored, so newly matched teams and fresh results count.
timeout 10m .venv/bin/python price.py --store --top 0 || echo "!! price.py exited $?"
# The tips (cs2.advice): rewritten until each match starts, locked from then on.
timeout 5m .venv/bin/python advice.py || echo "!! advice.py exited $?"

# Telegram, same bot and chat as the football and tennis tips: new CS2 tips,
# and the ones whose advice moved before the start. Credentials come from the
# web app's .env, like DATABASE_URL above.
TELEGRAM_BOT_TOKEN="$(.venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values("/home/app/scraper/.env").get("TELEGRAM_BOT_TOKEN") or "")')"
TELEGRAM_CHAT_ID="$(.venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values("/home/app/scraper/.env").get("TELEGRAM_CHAT_ID") or "")')"
export TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
timeout 5m .venv/bin/python notify.py || echo "!! notify.py exited $?"
echo "== $(date '+%F %T') done"
