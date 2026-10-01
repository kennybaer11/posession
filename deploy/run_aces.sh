#!/bin/bash
# Betano's WTA ace and double-fault odds for the aces project
# (github.com/kennybaer11/aces), which betken.cz's Tennis page shows.
#
# It runs here rather than on GitHub Actions because Betano refuses GitHub's
# runners. Self-contained: the first run clones the repo and builds its venv,
# later runs pull and reinstall only when requirements.txt changes. The
# database is posession's own, so DATABASE_URL is read from this app's .env
# rather than copied into a second file.
set -u
ACES=/home/app/aces
echo "== $(date '+%F %T') aces odds"

if [ ! -d "$ACES/.git" ]; then
    git clone -q https://github.com/kennybaer11/aces.git "$ACES" || exit 1
else
    git -C "$ACES" pull -q --ff-only || echo "!! git pull failed - running the code already here"
fi
cd "$ACES" || exit 1

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

timeout 20m .venv/bin/python odds.py || echo "!! odds.py exited $?"
echo "== $(date '+%F %T') done"
