"""Pre-match 1X2 odds from football-data.co.uk, stored as a model feature.

    python match_odds.py               this season's results + upcoming fixtures
    python match_odds.py --backfill    also last season (once)
    python match_odds.py --dry-run     match and report, write nothing

Why: the possession model only knew each team's own history. How strong a
favourite is explains possession beyond that - adding the de-vigged home-minus-
away win probability (p_diff) cut walk-forward error by 0.12 points over 1,014
matches in the three leagues (t=-2.1), measured 19 Sep 2026. Small but real.

The source publishes free CSVs (robots.txt allows everything). Results files
carry the average pre-closing odds of every played match; fixtures.csv carries
the upcoming ones and is refreshed a couple of times a week. So the data run
calls this hourly, and it only downloads when its last fetch is over
REFRESH_HOURS old.
"""

import argparse
import csv
import difflib
import io
import logging
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta

import requests

log = logging.getLogger("match_odds")

BASE = "https://football-data.co.uk"
FILES = {"PL": "E0", "LaLiga": "SP1", "BL1": "D1"}
REFRESH_HOURS = 6

# football-data's spellings that no token rule reaches.
ALIASES = {
    "man city": "Manchester City", "man united": "Manchester United",
    "nott'm forest": "Nottingham Forest", "wolves": "Wolverhampton Wanderers",
    "tottenham": "Tottenham Hotspur", "ipswich": "Ipswich Town",
    "ath madrid": "Atlético de Madrid", "ath bilbao": "Athletic Club",
    "betis": "Real Betis", "sociedad": "Real Sociedad",
    "espanol": "RCD Espanyol de Barcelona", "vallecano": "Rayo Vallecano",
    "la coruna": "RC Deportivo", "santander": "R. Racing Club",
    "m'gladbach": "Borussia Mönchengladbach", "ein frankfurt": "Eintracht Frankfurt",
    "fc koln": "1. FC Köln", "leverkusen": "Bayer 04 Leverkusen",
    "dortmund": "Borussia Dortmund", "bayern munich": "FC Bayern München",
    "mainz": "1. FSV Mainz 05", "union berlin": "1. FC Union Berlin",
    "st pauli": "FC St. Pauli", "heidenheim": "1. FC Heidenheim 1846",
    "hamburg": "Hamburger SV", "werder bremen": "SV Werder Bremen",
    "hoffenheim": "TSG Hoffenheim", "freiburg": "Sport-Club Freiburg",
    "stuttgart": "VfB Stuttgart", "wolfsburg": "VfL Wolfsburg",
    "augsburg": "FC Augsburg", "rb leipzig": "RB Leipzig",
    "paderborn": "SC Paderborn 07", "schalke 04": "FC Schalke 04",
    "elversberg": "SV Elversberg", "alaves": "Deportivo Alavés",
    "sevilla": "Sevilla FC", "valencia": "Valencia CF", "villarreal": "Villarreal CF",
    "getafe": "Getafe CF", "girona": "Girona FC", "osasuna": "CA Osasuna",
    "mallorca": "RCD Mallorca", "levante": "Levante UD", "elche": "Elche CF",
    "oviedo": "Real Oviedo", "barcelona": "FC Barcelona", "real madrid": "Real Madrid",
    "malaga": "Málaga CF",
}


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|afc|sc|sv|vfb|vfl|tsg|rcd|ca|ud|rc|cd|sd|fsv|bv|borussia"
               r"|club|de|real|and|hove|albion|united|city)\b", " ", s)
    return re.sub(r"[^a-z]+", " ", s).strip()


def resolver(names):
    """football-data name -> our team name, or None when unsure."""
    names = set(names)
    normed = {n: _norm(n) for n in names}

    def resolve(fd_name):
        alias = ALIASES.get(fd_name.lower().strip())
        if alias in names:
            return alias
        k = _norm(fd_name)
        exact = [n for n, v in normed.items() if v == k]
        if len(exact) == 1:
            return exact[0]
        close = difflib.get_close_matches(k, list(normed.values()), n=2, cutoff=0.75)
        if len(close) == 1 or (len(close) == 2 and close[0] != close[1]):
            hits = [n for n, v in normed.items() if v == close[0]]
            return hits[0] if len(hits) == 1 else None
        return None
    return resolve


def season_code(day):
    """2026-09-19 -> '2627' (seasons start in July)."""
    y = day.year if day.month >= 7 else day.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def _num(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def parse(text, division=None):
    """Rows of {div, date, home, away, odds_*} from a football-data CSV."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        div = (r.get("Div") or "").strip()
        if division and div != division:
            continue
        if not r.get("HomeTeam") or not r.get("Date"):
            continue
        d = r["Date"].strip()
        day = datetime.strptime(d, "%d/%m/%Y" if len(d) > 8 else "%d/%m/%y").date()
        h, dr, a = _num(r.get("AvgH")), _num(r.get("AvgD")), _num(r.get("AvgA"))
        if not (h and dr and a):
            continue
        inv = [1 / h, 1 / dr, 1 / a]
        total = sum(inv)
        out.append({"div": div, "date": day, "home": r["HomeTeam"].strip(),
                    "away": r["AwayTeam"].strip(), "odds_home": h, "odds_draw": dr,
                    "odds_away": a, "p_home": round(inv[0] / total, 4),
                    "p_draw": round(inv[1] / total, 4), "p_away": round(inv[2] / total, 4)})
    return out


def fetch(path):
    r = requests.get(f"{BASE}/{path}", timeout=30,
                     headers={"User-Agent": "posession.cz possession model"})
    r.raise_for_status()
    raw = r.content
    # The files start with a UTF-8 byte-order mark, which would otherwise
    # become part of the first column's name and hide "Div".
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def match_rows(db, competition, rows, source):
    """Attach match_id by league, date (+-1 day) and both team names."""
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT m.match_id, m.kickoff::date AS day, ht.name AS home, at_.name AS away
            FROM pl_matches m
            JOIN pl_teams ht  ON ht.team_id = m.home_team_id
            JOIN pl_teams at_ ON at_.team_id = m.away_team_id
            WHERE m.competition = %s""", (competition,))
        matches = cur.fetchall()
    resolve = resolver({m["home"] for m in matches} | {m["away"] for m in matches})
    by_pair = {}
    for m in matches:
        by_pair.setdefault((m["home"], m["away"]), []).append(m)
    found, unresolved, unmatched = [], set(), 0
    for r in rows:
        h, a = resolve(r["home"]), resolve(r["away"])
        if not h:
            unresolved.add(r["home"])
        if not a:
            unresolved.add(r["away"])
        if not (h and a):
            continue
        hits = [m for m in by_pair.get((h, a), [])
                if abs((m["day"] - r["date"]).days) <= 1]
        if len(hits) != 1:
            unmatched += 1
            continue
        found.append({"match_id": hits[0]["match_id"], "source": source,
                      **{k: r[k] for k in ("odds_home", "odds_draw", "odds_away",
                                           "p_home", "p_draw", "p_away")}})
    return found, unresolved, unmatched


def recently_fetched(db):
    with db.conn.cursor() as cur:
        cur.execute("""SELECT 1 FROM pl_match_odds
                       WHERE fetched_at > now() - (%s * INTERVAL '1 hour') LIMIT 1""",
                    (REFRESH_HOURS,))
        return cur.fetchone() is not None


def main():
    ap = argparse.ArgumentParser(description="Store pre-match 1X2 odds.")
    ap.add_argument("--backfill", action="store_true", help="also last season")
    ap.add_argument("--force", action="store_true", help="ignore the refresh interval")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    from dotenv import load_dotenv
    load_dotenv()
    from db import Database

    db = Database()
    db.ensure_schema(with_views=False)
    if not (args.force or args.backfill or args.dry_run) and recently_fetched(db):
        log.info("Odds fetched within %dh - nothing to do.", REFRESH_HOURS)
        db.close()
        return 0

    today = date.today()
    seasons = [season_code(today)]
    if args.backfill:
        seasons.insert(0, season_code(today - timedelta(days=365)))
    # Results first, then fixtures, so a match in both keeps the later figures.
    sources = [(f"mmz4281/{s}/{code}.csv", comp, code, f"football-data {s}")
               for s in seasons for comp, code in FILES.items()]
    sources += [("fixtures.csv", comp, code, "football-data fixtures")
                for comp, code in FILES.items()]

    cache, total, problems = {}, 0, 0
    for path, comp, code, source in sources:
        try:
            text = cache.get(path) or cache.setdefault(path, fetch(path))
        except requests.RequestException as exc:
            log.warning("could not fetch %s: %s", path, exc)
            problems += 1
            continue
        rows = parse(text, division=code)
        found, unresolved, unmatched = match_rows(db, comp, rows, source)
        log.info("%-6s %-28s %3d rows, %3d matched%s%s", comp, path, len(rows), len(found),
                 f", {unmatched} without a fixture" if unmatched else "",
                 f", unknown names {sorted(unresolved)}" if unresolved else "")
        problems += len(unresolved)
        if found and not args.dry_run:
            total += db.upsert_match_odds(found)
    log.info("%s %d match odds.", "Would write" if args.dry_run else "Wrote", total)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
