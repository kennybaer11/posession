"""Scrape Bundesliga or LaLiga into the same schema the Premier League uses.

    python scrape_league.py bundesliga --season 2026-2027
    python scrape_league.py laliga --season 2026 --weeks 6
    python scrape_league.py both --dry-run

main.py stays the Premier League's, because that feed is a real JSON API with
its own pagination, events and lineups. These two are page scrapes of a
different shape, so they get their own entry point rather than bending main.py
around three sources.

What they share is everything after fetching: the same tables, the same
columns, the same upserts. A match is a match once it is a row.
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

from db import Database

log = logging.getLogger("scrape_league")


def scrape_bundesliga(season, matchdays, refresh, db):
    import bundesliga_api as bl

    api = bl.BundesligaAPI()
    log.info("Bundesliga %s: reading matchdays...", season)
    matches = api.season_matches(season, matchdays)
    log.info("%d match(es) listed", len(matches))

    # The season label the database uses is the starting year, matching how
    # the Premier League rows are stored: "2026-2027" -> "2026".
    season_key = season.split("-")[0]

    teams, match_rows = {}, []
    for m in matches:
        for t in bl.team_rows(m):
            teams[t["team_id"]] = t
        match_rows.append(bl.match_row(m, season_key))

    known = set() if refresh else db.existing_match_ids(0)
    todo = [m for m in matches
            if m.get("matchStatus") == "FINAL_WHISTLE"
            and str(m["matchId"]) not in known
            and bl.slug_of(m)]
    log.info("%d played match(es) need stats (%d already stored)",
             len(todo), len(matches) - len(todo))

    stat_rows, failed = [], []
    for i, m in enumerate(todo, 1):
        log.info("[%d/%d] %s", i, len(todo), bl.slug_of(m))
        stats = api.match_stats(season, m.get("matchday"), bl.slug_of(m))
        built = bl.team_match_rows(m, season_key, stats)
        (stat_rows.extend(built) if built else failed.append(m["matchId"]))
    return list(teams.values()), match_rows, stat_rows, failed, api.request_count


def scrape_laliga(season, weeks, refresh, db):
    import laliga_api as ll

    api = ll.LaLigaAPI()
    log.info("LaLiga %s: reading matchdays...", season)
    matches = api.season_matches(weeks)
    log.info("%d match(es) listed", len(matches))

    teams, match_rows = {}, []
    for m in matches:
        for t in ll.team_rows(m):
            teams[t["team_id"]] = t
        match_rows.append(ll.match_row(m, season))

    known = set() if refresh else db.existing_match_ids(0)
    todo = [m for m in matches
            if m.get("status") == "FullTime" and str(m["id"]) not in known]
    log.info("%d played match(es) need stats (%d already stored)",
             len(todo), len(matches) - len(todo))

    stat_rows, failed = [], []
    for i, m in enumerate(todo, 1):
        log.info("[%d/%d] %s", i, len(todo), m["slug"][:60])
        payload = api.match_stats(m["slug"])
        built = ll.team_match_rows(m, season, (payload or {}).get("stats"))
        (stat_rows.extend(built) if built else failed.append(m["id"]))
    return list(teams.values()), match_rows, stat_rows, failed, api.request_count


def run(which, season, limit, refresh, dry_run, db):
    if which == "bundesliga":
        return scrape_bundesliga(season or "2026-2027", limit or 34, refresh, db)
    return scrape_laliga(season or "2026", limit or 38, refresh, db)


def main():
    ap = argparse.ArgumentParser(description="Scrape a non-English league.")
    ap.add_argument("league", choices=("bundesliga", "laliga", "both"))
    ap.add_argument("--season", help="bundesliga: 2026-2027, laliga: 2026")
    ap.add_argument("--weeks", "--matchdays", type=int, dest="limit",
                    help="how many matchdays to walk")
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch stats for matches already stored")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    load_dotenv()

    db = Database()
    db.ensure_schema(with_views=False)

    leagues = ("bundesliga", "laliga") if args.league == "both" else (args.league,)
    for which in leagues:
        teams, matches, stats, failed, requests_made = run(
            which, args.season, args.limit, args.refresh, args.dry_run, db)

        # Possession is zero-sum: if a league's rows do not average 50 the
        # sides have been paired wrongly, and that is worth knowing before it
        # reaches the database rather than after.
        poss = [float(r["possession"]) for r in stats
                if r.get("possession") is not None]
        mean = sum(poss) / len(poss) if poss else float("nan")
        log.info("%s: %d team(s), %d match(es), %d stat row(s), "
                 "%d failed, %d request(s)", which, len(teams), len(matches),
                 len(stats), len(failed), requests_made)
        log.info("  mean possession %.2f%% over %d row(s) %s",
                 mean, len(poss),
                 "OK" if abs(mean - 50) < 0.5 else "<-- NOT 50, sides may be mispaired")

        if args.dry_run:
            for r in stats[:4]:
                log.info("   %s poss=%s xg=%s passes=%s",
                         r["team_id"], r.get("possession"), r.get("xg"),
                         r.get("passes"))
            continue

        db.ensure_connection()
        db.upsert_teams(teams)
        db.upsert_matches(matches)
        if stats:
            db.upsert_team_matches(stats)
        log.info("  written.")

    if args.dry_run:
        log.info("--- dry run: nothing written ---")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
