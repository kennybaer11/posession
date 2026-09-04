"""Scrape Premier League match stats into a modelling-ready Postgres schema.

    python main.py --dry-run     # see what you'd get, write nothing
    python main.py               # scrape and write to the database
    python main.py --refresh     # re-fetch stats already stored

Writes pl_teams, pl_matches, pl_team_appearance and pl_team_match, plus the
views in views.sql - of which v_match_features is the training table and
v_fixture_features is what you predict against.

Needs DATABASE_URL in .env (the connection string from your Neon dashboard).
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml
from dotenv import load_dotenv

from db import Database
from features import AGAINST_STATS, ALL_COLUMNS, STAT_MAP, coerce
from pl_api import (OTHER_COMPETITIONS, PREMIER_LEAGUE_COMP_ID, PremierLeagueAPI)

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("main")


def json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if not cfg.get("premier_league"):
        sys.exit("config.yaml is missing the 'premier_league' section")
    return cfg["premier_league"]


def team_row(t):
    stadium = t.get("stadium") or {}
    return {
        "team_id": str(t["id"]),
        "name": t.get("name"),
        "short_name": t.get("shortName"),
        "abbr": t.get("abbr"),
        "stadium": stadium.get("name"),
        "city": stadium.get("city"),
        "capacity": stadium.get("capacity"),
    }


def match_row(m):
    home, away = m["homeTeam"], m["awayTeam"]
    return {
        "match_id": str(m["matchId"]),
        "season": str(m.get("season") or ""),
        "match_week": m.get("matchWeek"),
        "kickoff": m.get("kickoff"),
        "ground": m.get("ground"),
        "period": m.get("period"),
        "home_team_id": str(home["id"]),
        "away_team_id": str(away["id"]),
        "home_score": home.get("score"),
        "away_score": away.get("score"),
    }


def build_team_rows(match, stats_payload):
    """One row per team, carrying that team's own stat line."""
    if not stats_payload or len(stats_payload) != 2:
        return []

    by_team = {str(e["teamId"]): (e.get("stats") or {})
               for e in stats_payload if "teamId" in e}
    home, away = match["homeTeam"], match["awayTeam"]
    if str(home["id"]) not in by_team or str(away["id"]) not in by_team:
        log.warning("Match %s: stats teamIds %s don't match fixture teams",
                    match["matchId"], list(by_team))
        return []

    rows = []
    for team, opp, is_home in ((home, away, 1), (away, home, 0)):
        mine = by_team[str(team["id"])]
        theirs = by_team[str(opp["id"])]

        gf, ga = team.get("score"), opp.get("score")
        result = points = None
        if gf is not None and ga is not None:
            result = "W" if gf > ga else ("L" if gf < ga else "D")
            points = 3 if result == "W" else (1 if result == "D" else 0)

        row = {
            "match_id": str(match["matchId"]),
            "team_id": str(team["id"]),
            "opponent_id": str(opp["id"]),
            "is_home": is_home,
            "season": str(match.get("season") or ""),
            "match_week": match.get("matchWeek"),
            "kickoff": match.get("kickoff"),
            "result": result,
            "points": points,
        }
        for col, api_key in STAT_MAP.items():
            row[col] = coerce(mine.get(api_key), col)
        for col, api_key in AGAINST_STATS.items():
            # "against" is the opponent's own figure, read from the payload
            # rather than derived, so a data oddity surfaces instead of hiding.
            row[col] = coerce(theirs.get(api_key), col)
        rows.append(row)
    return rows


def _minute(value):
    """Event minutes arrive as strings, and stoppage time as '90+3' or '45+2'."""
    if value is None:
        return None
    text = str(value).strip()
    if "+" in text:
        base, _, extra = text.partition("+")
        try:
            return int(base) + int(extra or 0)
        except ValueError:
            return None
    try:
        return int(text)
    except ValueError:
        return None


def event_rows(match, payload):
    """Goals, cards and subs for one match, as three lists of rows.

    Returns ([], [], []) rather than raising when the payload is missing: not
    every match has events published immediately, and a match without them
    should not sink the whole run.
    """
    if not payload:
        return [], [], []

    match_id = str(match["matchId"])
    sides = (("homeTeam", match["homeTeam"]), ("awayTeam", match["awayTeam"]))
    goals, cards, subs = [], [], []

    for key, team in sides:
        block = payload.get(key) or {}
        team_id = str(team["id"])

        for g in block.get("goals") or []:
            minute = _minute(g.get("time"))
            if minute is None:
                continue
            goals.append({
                "match_id": match_id,
                "team_id": team_id,          # the side the goal counts FOR
                "minute": minute,
                "period": g.get("period"),
                "goal_type": g.get("goalType"),
                "player_id": str(g.get("playerId") or ""),
                "assist_player_id": (str(g["assistPlayerId"])
                                     if g.get("assistPlayerId") else None),
            })

        for c in block.get("cards") or []:
            minute = _minute(c.get("time"))
            if minute is None or not c.get("playerId"):
                continue
            cards.append({
                "match_id": match_id,
                "team_id": team_id,
                "minute": minute,
                "period": c.get("period"),
                "card_type": c.get("type"),
                "player_id": str(c["playerId"]),
            })

        for s in block.get("subs") or []:
            minute = _minute(s.get("time"))
            if minute is None or not s.get("playerOnId"):
                continue
            subs.append({
                "match_id": match_id,
                "team_id": team_id,
                "minute": minute,
                "period": s.get("period"),
                "player_on_id": str(s["playerOnId"]),
                "player_off_id": (str(s["playerOffId"])
                                  if s.get("playerOffId") else None),
            })

    return goals, cards, subs


def lineup_rows(match, payload):
    """Starting XI and bench for one match, plus the players seen.

    line_index is what makes this worth storing: the API's `position` field
    says "Midfielder" for a holding player and a number 10 alike, but the
    formation's `lineup` rows separate them.
    """
    if not payload:
        return [], []

    match_id = str(match["matchId"])
    rows, players = [], []

    for key, team in (("home_team", match["homeTeam"]),
                      ("away_team", match["awayTeam"])):
        block = payload.get(key) or {}
        team_id = str(team["id"])
        formation = block.get("formation") or {}
        shape = formation.get("formation")

        # player_id -> which band of the formation they start in
        line_of = {}
        for idx, band in enumerate(formation.get("lineup") or []):
            for pid in band:
                line_of[str(pid)] = idx
        starters = set(line_of)

        for p in block.get("players") or []:
            pid = str(p.get("id") or "")
            if not pid:
                continue
            rows.append({
                "match_id": match_id,
                "team_id": team_id,
                "player_id": pid,
                "position": p.get("position"),
                "shirt_num": p.get("shirtNum"),
                "is_captain": 1 if p.get("isCaptain") else 0,
                "is_starter": 1 if pid in starters else 0,
                "line_index": line_of.get(pid),
                "formation": shape,
            })
            players.append({
                "player_id": pid,
                "first_name": p.get("firstName"),
                "last_name": p.get("lastName"),
            })

    return rows, players


def appearance_rows(match, competition_id, competition_name, team_ids):
    """Calendar entries for whichever tracked teams played in this match."""
    home, away = match["homeTeam"], match["awayTeam"]
    rows = []
    for team, opp, is_home in ((home, away, 1), (away, home, 0)):
        if str(team["id"]) not in team_ids:
            continue
        rows.append({
            "match_id": str(match["matchId"]),
            "team_id": str(team["id"]),
            "competition_id": str(competition_id),
            "competition": competition_name,
            "season": str(match.get("season") or ""),
            "kickoff": match.get("kickoff"),
            "is_home": is_home,
            "opponent_id": str(opp["id"]),
            "opponent_name": opp.get("name"),
            "period": match.get("period"),
            "goals_for": team.get("score"),
            "goals_against": opp.get("score"),
        })
    return rows


def build_calendar(api, seasons, team_ids, pl_matches, upcoming):
    """Every competitive fixture our tracked teams play, in any competition.

    Rest days are meaningless from league games alone: a side playing Thursday
    in Europe then Sunday in the league has 3 days off, not 7.
    """
    rows = []
    for m in list(pl_matches) + list(upcoming):
        rows += appearance_rows(m, PREMIER_LEAGUE_COMP_ID, "Premier League", team_ids)

    for comp_id, comp_name in OTHER_COMPETITIONS.items():
        for season in seasons:
            matches = api.competition_matches(comp_id, season)
            hits = []
            for m in matches:
                hits += appearance_rows(m, comp_id, comp_name, team_ids)
            if hits:
                log.info("  %s %s: %d appearance(s)", comp_name, season, len(hits))
            rows += hits

    # A club can appear twice for one match id across competitions only if the
    # API repeats it; keep the last write per (match, team).
    deduped = {}
    for r in rows:
        deduped[(r["match_id"], r["team_id"])] = r
    return list(deduped.values())


def collect_matches(api, seasons, matches_per_team, team_ids):
    """Walk seasons newest-first until every team has enough matches."""
    per_team = {tid: [] for tid in team_ids}
    matches_by_id = {}
    for season in seasons:
        if all(len(v) >= matches_per_team for v in per_team.values()):
            break
        log.info("Reading season %s...", season)
        for match in api.completed_matches(season):
            for tid in (str(match["homeTeam"]["id"]), str(match["awayTeam"]["id"])):
                if tid in per_team and len(per_team[tid]) < matches_per_team:
                    per_team[tid].append(str(match["matchId"]))
                    matches_by_id[str(match["matchId"])] = match
    return per_team, matches_by_id


def main():
    ap = argparse.ArgumentParser(
        description="Scrape Premier League stats into a modelling schema.")
    ap.add_argument("--config", default=str(BASE_DIR / "config.yaml"))
    ap.add_argument("--matches", type=int, help="matches per team")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch stats for matches already stored")
    ap.add_argument("--no-detail", action="store_true",
                    help="skip goal/card/sub events and lineups (2 fewer "
                         "requests per match)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    load_dotenv(BASE_DIR / ".env")

    cfg = load_config(args.config)
    target = args.matches or int(cfg.get("matches_per_team", 10))
    seasons = [str(s) for s in cfg["seasons"]]
    # Events and lineups cost 2 extra requests per NEW match. Settled matches
    # are skipped like stats are, so a routine hourly run pays nothing.
    collect_detail = (not args.no_detail
                      and bool(cfg.get("collect_detail", True))
                      and not args.dry_run)

    api = PremierLeagueAPI(
        delay_seconds=cfg.get("delay_seconds", 1.0),
        timeout=cfg.get("timeout_seconds", 25),
        retries=cfg.get("retries", 3))

    # Connect before any scraping. A bad connection string should surface in
    # one second, not after two minutes of API calls.
    db = None
    if not args.dry_run:
        db = connect_or_explain()
        db.ensure_schema()

    # 1. Teams
    teams_raw = api.teams(seasons[0])
    if not teams_raw:
        log.error("Could not load the team list - the API may have changed.")
        return 1
    teams = [team_row(t) for t in teams_raw]
    team_names = {t["team_id"]: t["name"] for t in teams}
    log.info("Season %s has %d teams", seasons[0], len(teams))

    # 2. Completed matches making up each team's last N
    per_team, matches_by_id = collect_matches(api, seasons, target, set(team_names))
    short = {team_names[t]: len(m) for t, m in per_team.items() if len(m) < target}
    if short:
        log.warning("Fewer than %d matches available for: %s", target,
                    ", ".join(f"{n} ({c})" for n, c in sorted(short.items())))

    # 3. Upcoming fixtures - the rows you predict against
    upcoming = api.upcoming_matches(seasons[0],
                                    limit=int(cfg.get("upcoming_fixtures", 20)))
    log.info("%d upcoming fixture(s) stored for prediction", len(upcoming))

    all_matches = [match_row(m) for m in matches_by_id.values()] \
                + [match_row(m) for m in upcoming]

    # 3b. All-competition calendar, so rest days reflect European and cup games
    log.info("Building all-competition calendar for rest days...")
    calendar = build_calendar(api, seasons, set(team_names),
                              matches_by_id.values(), upcoming)
    log.info("%d appearance(s) across all competitions", len(calendar))

    needed = sorted(matches_by_id)
    if db is not None:
        if not args.refresh:
            known = db.existing_match_ids(int(cfg.get("recheck_hours", 48)))
            skip = [m for m in needed if m in known]
            if skip:
                log.info("Skipping %d settled match(es) already stored", len(skip))
                needed = [m for m in needed if m not in known]

    # 4. Per-match stats, plus events and lineups
    rows, failed = [], []
    goals_all, cards_all, subs_all, lineups_all, players_all = [], [], [], [], []
    event_matches = []
    for i, mid in enumerate(needed, 1):
        match = matches_by_id[mid]
        log.info("[%d/%d] stats for match %s (%s v %s)", i, len(needed), mid,
                 match["homeTeam"]["abbr"], match["awayTeam"]["abbr"])
        built = build_team_rows(match, api.match_stats(mid))
        if built:
            # Store BOTH sides of every match we fetch, not just the team that
            # asked for it. A half-stored match leaves the opponent's form
            # unavailable, which breaks the features for that fixture - and the
            # second row is free, since the stats call returns both anyway.
            rows.extend(built)
        else:
            failed.append(mid)

        if collect_detail:
            g, c, s = event_rows(match, api.match_events(mid))
            lu, pl = lineup_rows(match, api.match_lineups(mid))
            # Only mark the match for an event wipe if something came back, so
            # a failed fetch cannot silently delete events already stored.
            if g or c or s:
                event_matches.append(mid)
                goals_all += g
                cards_all += c
                subs_all += s
            lineups_all += lu
            players_all += pl

    if failed:
        log.warning("No usable stats for %d match(es): %s",
                    len(failed), ", ".join(failed[:10]))
    missing_xg = sum(1 for r in rows if not r.get("xg"))
    if missing_xg:
        log.warning("%d row(s) have no xG - the API may have renamed a field",
                    missing_xg)

    if not rows:
        log.error("Nothing to write.")
        if db:
            db.close()
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = BASE_DIR / "output" / f"pl-stats-{stamp}.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False,
                                   default=json_default), encoding="utf-8")
    log.info("Saved %d team-match row(s) to %s (%d API requests)",
             len(rows), out_path, api.request_count)

    if args.dry_run:
        for r in rows[:3]:
            print(f"  {team_names.get(r['team_id'], r['team_id']):<24} "
                  f"{r['kickoff']}  poss {r['possession']}  xG {r['xg']}  "
                  f"shots {r['shots']} (SoT {r['shots_on_target']})  {r['result']}")

    if args.dry_run:
        print("\n--- dry run: nothing written to the database ---")
        return 0

    try:
        # The scrape above can run for minutes; the pooler may have hung up.
        db.ensure_connection()
        db.upsert_teams(teams)
        db.upsert_matches(all_matches)
        db.upsert_appearances(calendar)
        res = db.upsert_team_matches(rows)
        log.info("Wrote %d team(s), %d match(es), %d appearance(s), %d stat row(s). "
                 "pl_team_match holds %d row(s).",
                 len(teams), len(all_matches), len(calendar), res["written"],
                 db.count())

        if collect_detail:
            by_match = {mid: ([], [], []) for mid in event_matches}
            for r in goals_all:
                by_match[r["match_id"]][0].append(r)
            for r in cards_all:
                by_match[r["match_id"]][1].append(r)
            for r in subs_all:
                by_match[r["match_id"]][2].append(r)
            for mid, (g, c, s) in by_match.items():
                db.replace_match_events(mid, g, c, s)

            # Players first: pl_lineup rows point at them.
            seen = {p["player_id"]: p for p in players_all}
            db.upsert_players(list(seen.values()))
            db.upsert_lineups(lineups_all)
            log.info("Wrote %d goal(s), %d card(s), %d sub(s), %d lineup row(s), "
                     "%d player(s).", len(goals_all), len(cards_all),
                     len(subs_all), len(lineups_all), len(seen))
    finally:
        db.close()
    return 0


def connect_or_explain():
    """Connect, turning the usual failures into plain English."""
    try:
        return Database()
    except Exception as exc:
        sys.exit(
            f"Could not connect to Postgres: {exc}\n\n"
            "  Check DATABASE_URL in .env - it should be the connection "
            "string\n  from your Neon dashboard, ending in ?sslmode=require"
        )


if __name__ == "__main__":
    sys.exit(main())
