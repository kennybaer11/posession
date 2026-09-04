"""Client for the Premier League site's own JSON API.

The premierleague.com match pages are a JavaScript app - the HTML shell contains
no stats at all. The page fetches them from these endpoints, which is what we
use. Discovered by watching the network tab on a match stats page; they need no
authentication, only a browser-ish Origin/Referer.

  GET /api/v1/competitions/8/seasons/{season}/teams
  GET /api/v2/matches?competition=8&season={season}&period=FullTime&_sort=kickoff:desc
  GET /api/v3/matches/{matchId}/stats

Being an undocumented internal API, field names can change without warning.
main.py fails loudly rather than silently writing NULLs if that happens.
"""

import logging
import time

import requests

log = logging.getLogger(__name__)

BASE = "https://sdp-prem-prod.premier-league-prod.pulselive.com/api"
PREMIER_LEAGUE_COMP_ID = 8
PAGE_LIMIT = 100  # server caps _limit at 100 regardless of what we ask for

# Competitions an English top-flight club can play in. Used only to work out
# real rest days - a team playing Thursday in Europe then Sunday in the league
# has 3 days off, not the 7 a league-only calendar would show.
# (Verified: the same team ids are used across all of these.)
OTHER_COMPETITIONS = {
    5: "UEFA Champions League",
    6: "UEFA Europa League",
    1125: "UEFA Conference League",
    1: "FA Cup",
    2: "EFL Cup",
    38: "Community Shield",
}


class PremierLeagueAPI:
    def __init__(self, delay_seconds=1.0, timeout=25, retries=3):
        self.delay = float(delay_seconds)
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Origin": "https://www.premierleague.com",
            "Referer": "https://www.premierleague.com/",
            "Accept": "application/json",
        })
        self._last_call = 0.0
        self.request_count = 0

    def _get(self, path, params=None):
        gap = time.monotonic() - self._last_call
        if gap < self.delay:
            time.sleep(self.delay - gap)

        url = f"{BASE}{path}"
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                self._last_call = time.monotonic()
                self.request_count += 1
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = self.delay * (2 ** attempt)
                    log.warning("HTTP %s on %s - backing off %.1fs",
                                resp.status_code, path, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("Attempt %d/%d failed for %s: %s",
                            attempt, self.retries, path, exc)
                if attempt == self.retries:
                    return None
                time.sleep(self.delay * (2 ** attempt))
        return None

    # -- endpoints ---------------------------------------------------------

    def teams(self, season):
        """The 20 clubs in a given season. season is the start year, e.g. 2026."""
        payload = self._get(
            f"/v1/competitions/{PREMIER_LEAGUE_COMP_ID}/seasons/{season}/teams",
            {"_limit": 25},
        )
        return (payload or {}).get("data", [])

    def completed_matches(self, season, max_matches=None):
        """Completed matches for a season, newest first, following the cursor."""
        out, cursor = [], None
        while True:
            params = {
                "competition": PREMIER_LEAGUE_COMP_ID,
                "season": season,
                "period": "FullTime",
                "_sort": "kickoff:desc",
                "_limit": PAGE_LIMIT,
            }
            if cursor:
                params["_next"] = cursor

            payload = self._get("/v2/matches", params)
            if not payload:
                break
            rows = payload.get("data", [])
            out.extend(rows)
            log.info("Season %s: fetched %d completed match(es) so far", season, len(out))

            cursor = payload.get("pagination", {}).get("_next")
            if not cursor or not rows:
                break
            if max_matches and len(out) >= max_matches:
                break
        return out

    def competition_matches(self, competition_id, season, period=None, max_pages=6):
        """All matches in any competition, newest first.

        Used to build the rest-day calendar: a team's real gap between games is
        driven by midweek European and cup fixtures, not just league ones.
        Team IDs are shared across competitions, so these join straight on.
        """
        out, cursor = [], None
        for _ in range(max_pages):
            params = {
                "competition": competition_id,
                "season": season,
                "_sort": "kickoff:desc",
                "_limit": PAGE_LIMIT,
            }
            if period:
                params["period"] = period
            if cursor:
                params["_next"] = cursor

            payload = self._get("/v2/matches", params)
            if not payload:
                break
            rows = payload.get("data", [])
            out.extend(rows)
            cursor = payload.get("pagination", {}).get("_next")
            if not cursor or not rows:
                break
        return out

    def upcoming_matches(self, season, limit=PAGE_LIMIT):
        """Scheduled matches, soonest first - the rows you predict against."""
        payload = self._get("/v2/matches", {
            "competition": PREMIER_LEAGUE_COMP_ID,
            "season": season,
            "period": "PreMatch",
            "_sort": "kickoff:asc",
            "_limit": min(limit, PAGE_LIMIT),
        })
        return (payload or {}).get("data", [])

    def match_stats(self, match_id):
        """Per-team stats for one match: a 2-element list, one entry per side."""
        return self._get(f"/v3/matches/{match_id}/stats")

    def match_events(self, match_id):
        """Goals, cards and substitutions with the minute each happened.

        Shape: {"homeTeam": {...}, "awayTeam": {...}}, each side carrying
        goals / cards / subs lists. Note this is /v1 - the /v3 path 400s.

        Own goals are listed under the team they COUNT FOR, not the team of the
        player who scored them. Checked against 30 matches: goal counts matched
        every stored scoreline, which they would not if own goals sat with the
        scorer's side.
        """
        return self._get(f"/v1/matches/{match_id}/events")

    def match_lineups(self, match_id):
        """Starting XI, bench and formation.

        Shape: {"home_team": {...}, "away_team": {...}} - note the underscores,
        where the events endpoint uses camelCase. Each side has `players`
        (id, name, position, shirtNum, isCaptain) and `formation`, whose
        `lineup` is a list of rows: [[GK], [defenders], [midfield band], ...].
        The row a player sits in is the only way to tell a holding midfielder
        from an attacking one - `position` says "Midfielder" for both.
        """
        return self._get(f"/v3/matches/{match_id}/lineups")
