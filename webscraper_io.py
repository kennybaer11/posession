"""Pull finished webscraper.io jobs straight into the odds table.

    python webscraper_io.py --list                 recent jobs
    python webscraper_io.py --job 45692638         import one, with a preview
    python webscraper_io.py --job 45692638 --write actually write it

Needs WEBSCRAPER_TOKEN in .env.

The parsing is shared with the file and paste importers - this module only
fetches. A second parser would eventually disagree with the first about what
a row means, and for odds that means recording the wrong bet.

One thing this cannot fix: webscraper.io's cloud renders pages in its own
timezone, so the kickoff time in a scraped row is hours out and can name the
wrong day. The date is discarded and matches are found by club pair instead -
see odds_sheet.parse_webscraper.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API = "https://api.webscraper.io/api/v1"


def token():
    tok = os.getenv("WEBSCRAPER_TOKEN")
    if not tok:
        raise SystemExit(
            "WEBSCRAPER_TOKEN is not set. Add it to .env - see .env.example.")
    return tok


def _get(path, **params):
    params["api_token"] = token()
    r = requests.get(f"{API}{path}", params=params, timeout=40)
    r.raise_for_status()
    return r


def jobs(limit=10):
    return (_get("/scraping-jobs").json().get("data") or [])[:limit]


def job_rows(job_id):
    """A finished job's scraped records. The endpoint returns JSON Lines."""
    text = _get(f"/scraping-job/{job_id}/json").text
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser(description="Import a webscraper.io job.")
    ap.add_argument("--list", action="store_true", help="show recent jobs")
    ap.add_argument("--job", type=int, help="scraping job id to import")
    ap.add_argument("--write", action="store_true",
                    help="write to the database (otherwise preview only)")
    ap.add_argument("--bookmaker", default="chance.cz")
    args = ap.parse_args()

    if args.list or not args.job:
        for j in jobs():
            print(f"  {j.get('id'):>10}  {str(j.get('sitemap_name'))[:34]:34} "
                  f"{str(j.get('status')):10} "
                  f"{j.get('stored_record_count')} record(s)"
                  f"{'  [test run]' if j.get('test_run') else ''}")
        if not args.job:
            return 0

    rows = job_rows(args.job)
    print(f"\njob {args.job}: {len(rows)} record(s) fetched")
    if not rows:
        return 1

    import odds_sheet
    import import_odds as io_mod
    from db import Database

    parsed = odds_sheet.parse_webscraper(rows)
    print(f"  {len(parsed)} understood as possession lines\n")

    db = Database()
    db.ensure_schema(with_views=False)
    ready, problems = io_mod.resolve_rows(db, parsed, args.bookmaker)

    for r in ready:
        both = "both prices" if r["over_odds"] and r["under_odds"] else "one price"
        print(f"  ok   {r['_label']}  over {r['over_odds']} / "
              f"under {r['under_odds']}  [{both}]")
    for p in problems:
        print(f"  --   {p}")

    if not args.write:
        print("\n--- preview only: pass --write to import ---")
        return 0
    if not ready:
        return 1

    for r in ready:
        r.pop("_label", None)
        r.pop("_flipped", None)
    print(f"\nWrote {db.upsert_lines(ready)} line(s).")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
