"""Client for bundesliga.com.

There is no open JSON API here. `wapp.bapi.bundesliga.com` returns 403 without
a key, including from the site's own pages - so that route is deliberately not
taken. What IS public is the rendered page: bundesliga.com is an Angular app
that server-renders its data into a `<script id="ng-state">` block, and a plain
GET returns it in full.

Two pages are needed:

    /de/bundesliga/spieltag/{season}/{matchday}
        every match on that matchday - id, slug, kickoff, score, status

    /de/bundesliga/spieltag/{season}/{matchday}/{slug}/stats
        that match's team stats, including ballPossessionRatio

The state is keyed by Firebase paths, so the values are looked up by the shape
of the key rather than a fixed name - those hashes change between deploys.

Possession here is a whole number (53, not 53.2), coarser than the Premier
League and Spanish feeds. Worth remembering when comparing model error across
leagues: some of Bundesliga's will be rounding, not misprediction.
"""

import json
import logging
import re
import time

import requests

log = logging.getLogger(__name__)

BASE = "https://www.bundesliga.com"
COMPETITION = "BL1"

def qualify(raw):
    """Prefix an id with the competition.

    LaLiga numbers its clubs 2, 3, 4, 14 - exactly like the Premier League, so
    "3" is Athletic Club here and Arsenal there. Sharing a primary key let one
    league's upsert overwrite the other's rows. The prefix makes ids unique
    across leagues, which the schema always assumed and never enforced.
    """
    return None if raw is None else COMPETITION + ":" + str(raw)


_STATE_RE = re.compile(
    r'<script id="ng-state" type="application/json">(.*?)</script>', re.S)


class BundesligaAPI:
    def __init__(self, delay_seconds=1.0, timeout=30, retries=3):
        self.delay = float(delay_seconds)
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "de,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        })
        self._last_call = 0.0
        self.request_count = 0

    # -- plumbing ----------------------------------------------------------

    def _get_state(self, path):
        """Fetch a page and return its ng-state as a dict, or None."""
        gap = time.monotonic() - self._last_call
        if gap < self.delay:
            time.sleep(self.delay - gap)

        url = f"{BASE}{path}"
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                self._last_call = time.monotonic()
                self.request_count += 1
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = self.delay * (2 ** attempt)
                    log.warning("HTTP %s on %s - backing off %.1fs",
                                resp.status_code, path, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                m = _STATE_RE.search(resp.text)
                if not m:
                    log.warning("No ng-state in %s - the page layout may have "
                                "changed", path)
                    return None
                return json.loads(m.group(1))
            except (requests.RequestException, ValueError) as exc:
                log.warning("Attempt %d/%d failed for %s: %s",
                            attempt, self.retries, path, exc)
                if attempt == self.retries:
                    return None
                time.sleep(self.delay * (2 ** attempt))
        return None

    @staticmethod
    def _find(state, predicate):
        """First state value whose KEY satisfies predicate.

        Half the keys are content hashes that change on every deploy, so
        nothing may be looked up by a literal name. The Firebase paths are
        stable in shape, and that shape is what is matched.
        """
        if not state:
            return None
        for key, value in state.items():
            if predicate(key):
                return value
        return None

    # -- endpoints ---------------------------------------------------------

    def matchday(self, season, matchday):
        """Every match on one matchday. season is like '2026-2027'.

        A page can carry more than one matchday list. A past season's matchday
        page that shares its number with the CURRENT matchday also embeds the
        current one as a widget, under a key for a different season id - and
        taking the first match meant /spieltag/2025-2026/3 filed this weekend's
        matchday 3 as last season's. So every candidate list is collected and
        the one whose kickoffs fall inside the requested season is used; if
        none do, nothing is returned rather than the wrong season.
        """
        state = self._get_state(f"/de/bundesliga/spieltag/{season}/{matchday}")
        if not state:
            return []
        # Keys end "matchesmatchday" + number + a two-digit suffix, e.g.
        # matchesmatchday399 for 3 and matchesmatchday3399 for 33. Without the
        # lookahead "3" would also match matchday 30-34.
        # Doubled braces: this is an f-string, and a bare {3} would be evaluated
        # to the digit 3, turning the lookahead into "not followed by digit-3".
        want = re.compile(rf"matchesmatchday{int(matchday)}(?!\d{{3}})")
        start = int(str(season)[:4])
        lo, hi = f"{start}-07-01", f"{start + 1}-07-01"
        candidates = []
        for key, data in state.items():
            if not want.search(key):
                continue
            items = data if isinstance(data, list) else list((data or {}).values())
            rows = [m for m in items if isinstance(m, dict) and m.get("matchId")]
            if rows:
                candidates.append(rows)
        for rows in candidates:
            kickoffs = [(m.get("plannedKickOff") or "")[:10] for m in rows]
            if kickoffs and all(lo <= k < hi for k in kickoffs):
                return rows
        if candidates:
            log.warning("Matchday %s of %s: %d list(s) on the page, none inside "
                        "the season - skipping", matchday, season, len(candidates))
        return []

    def season_matches(self, season, matchdays=34):
        """Walk every matchday. 34 in a Bundesliga season, 18 clubs."""
        out = []
        for md in range(1, matchdays + 1):
            rows = self.matchday(season, md)
            if not rows:
                log.info("  matchday %s: nothing returned, stopping", md)
                break
            out.extend(rows)
            log.info("  matchday %s: %d match(es)", md, len(rows))
        return out

    def match_stats(self, season, matchday, slug):
        """Team stats for one match, as {stat: {homeValue, awayValue}}."""
        state = self._get_state(
            f"/de/bundesliga/spieltag/{season}/{matchday}/{slug}/stats")
        return self._find(state, lambda k: k.endswith("/stats"))


def slug_of(match):
    return (match.get("slugs") or {}).get("slugLong")


def team_rows(match):
    """The two clubs in a match, in this project's team shape."""
    rows = []
    for side in ("home", "away"):
        t = (match.get("teams") or {}).get(side) or {}
        tid = t.get("dflDatalibraryClubId") or t.get("clubId") or t.get("id")
        if not tid:
            continue
        rows.append({
            "competition": COMPETITION,
            "team_id": qualify(tid),
            "name": t.get("nameFull") or t.get("name"),
            "short_name": t.get("nameShort") or t.get("threeLetterCode"),
            "abbr": t.get("threeLetterCode"),
            "stadium": None, "city": None, "capacity": None,
        })
    return rows


# Bundesliga's stat names -> this project's columns. A deliberate subset: the
# feed publishes about a dozen stats where the Premier League's gives 171.
#
# Columns this feed does NOT publish are left NULL, never 0. features.py
# coalesces a missing COUNT to zero because in the PL feed an absent stat means
# "it never happened" - no red card, no save. Here an absent stat means "this
# league does not publish it", and writing 0 would tell every average that
# Bundesliga sides make no tackles.
BL_STAT_MAP = {
    "possession":        "ballPossessionRatio",
    "xg":                "XGoals",
    "corners":           "cornerKicks",
    "fouls":             "fouls",
    "offsides":          "offsides",
    "passes":            "passes",
    "shots_on_target":   "shotsOnTarget",
    "shots_off_target":  "shotsOffTarget",
    "tackles_won":       "tacklesWon",
}

# passAccuracy is published as a percentage (80, 88) where every other feed
# gives a count of completed passes, and pass_accuracy_l5 divides the count by
# the volume. Multiplying back is exact to within rounding: the feed rounds the
# percentage to a whole number, so 350 passes at 80% recovers 280 where the
# true figure might be 279 or 281. That error is a fraction of a percent of a
# ratio already averaged over five matches.
BL_DERIVED = {"passes_accurate": ("passes", "passAccuracy")}

BL_AGAINST = {
    "possession_against": "ballPossessionRatio",
    "xg_against":         "XGoals",
    "shots_on_target_against": "shotsOnTarget",
}


def _side(stats, key, side):
    """One side's value for a stat, or None when the feed omits it."""
    entry = (stats or {}).get(key)
    if not isinstance(entry, dict):
        return None
    return entry.get(f"{side}Value")


def match_row(match, season):
    """A match in this project's shape."""
    teams = match.get("teams") or {}
    home = (teams.get("home") or {}).get("dflDatalibraryClubId")
    away = (teams.get("away") or {}).get("dflDatalibraryClubId")
    score = match.get("score") or {}
    finished = match.get("matchStatus") == "FINAL_WHISTLE"
    return {
        "competition": COMPETITION,
        "match_id": qualify(match["matchId"]),
        "season": str(season),
        "match_week": match.get("matchday"),
        # Stored naive, like every other kickoff here, so the form windows
        # order consistently across leagues.
        "kickoff": (match.get("plannedKickOff") or match.get("kickOff") or
                    "")[:19].replace("T", " ") or None,
        "ground": None,
        "period": "FullTime" if finished else "PreMatch",
        "home_team_id": qualify(home),
        "away_team_id": qualify(away),
        "home_score": (score.get("home") or {}).get("fulltime") if finished else None,
        "away_score": (score.get("away") or {}).get("fulltime") if finished else None,
    }


def team_match_rows(match, season, stats):
    """One row per team, carrying that team's own stat line."""
    if not stats:
        return []
    teams = match.get("teams") or {}
    home_id = (teams.get("home") or {}).get("dflDatalibraryClubId")
    away_id = (teams.get("away") or {}).get("dflDatalibraryClubId")
    if not (home_id and away_id):
        return []

    score = match.get("score") or {}
    gf = (score.get("home") or {}).get("fulltime")
    ga = (score.get("away") or {}).get("fulltime")
    if gf is None or ga is None:
        return []

    rows = []
    for side, tid, oid, is_home in (("home", home_id, away_id, 1),
                                    ("away", away_id, home_id, 0)):
        mine, theirs = (gf, ga) if is_home else (ga, gf)
        result = "W" if mine > theirs else ("L" if mine < theirs else "D")
        other = "away" if is_home else "home"
        row = {
            "competition": COMPETITION,
            "match_id": qualify(match["matchId"]),
            "team_id": qualify(tid), "opponent_id": qualify(oid),
            "is_home": is_home,
            "season": str(season),
            "match_week": match.get("matchday"),
            "kickoff": (match.get("plannedKickOff") or "")[:19].replace("T", " ") or None,
            "result": result,
            "points": 3 if result == "W" else (1 if result == "D" else 0),
            "goals": mine, "goals_against": theirs,
        }
        for col, key in BL_STAT_MAP.items():
            row[col] = _side(stats, key, side)
        for col, key in BL_AGAINST.items():
            row[col] = _side(stats, key, other)
        for col, (vol_key, pct_key) in BL_DERIVED.items():
            vol, pct = _side(stats, vol_key, side), _side(stats, pct_key, side)
            row[col] = (round(float(vol) * float(pct) / 100.0)
                        if vol is not None and pct is not None else None)
        rows.append(row)
    return rows
