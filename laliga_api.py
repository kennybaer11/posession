"""Client for laliga.com (LALIGA EA SPORTS - the men's first division).

Like bundesliga.com there is no open JSON API, and like it the rendered page
carries everything: laliga.com is a Next.js app that embeds its data in a
`<script id="__NEXT_DATA__">` block, returned in full to a plain GET.

    /en-GB/laliga-easports/results?week={n}   every match that matchday
    /en-GB/match/{slug}                        that match's full team stats

`?week=` is the parameter that moves between matchdays. It is the only one
that does - gameweek, jornada, gw, matchday, round and gameweekId are all
accepted and all silently ignored, returning the current week, which would
quietly scrape the same ten matches 38 times.

The payload is the richest of the three leagues: the same Opta feed the
Premier League API serves, in snake_case rather than camelCase, so most of
features.py maps across directly.
"""

import json
import logging
import re
import time

import requests

log = logging.getLogger(__name__)

BASE = "https://www.laliga.com"
COMPETITION = "LaLiga"

def qualify(raw):
    """Prefix an id with the competition.

    LaLiga numbers its clubs 2, 3, 4, 14 - exactly like the Premier League, so
    "3" is Athletic Club here and Arsenal there. Sharing a primary key let one
    league's upsert overwrite the other's rows. The prefix makes ids unique
    across leagues, which the schema always assumed and never enforced.
    """
    return None if raw is None else COMPETITION + ":" + str(raw)


_NEXT_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class LaLigaAPI:
    def __init__(self, delay_seconds=1.0, timeout=30, retries=3):
        self.delay = float(delay_seconds)
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "en,es;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        })
        self._last_call = 0.0
        self.request_count = 0

    def _page_props(self, path):
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
                m = _NEXT_RE.search(resp.text)
                if not m:
                    log.warning("No __NEXT_DATA__ in %s", path)
                    return None
                return json.loads(m.group(1))["props"]["pageProps"]
            except (requests.RequestException, ValueError, KeyError) as exc:
                log.warning("Attempt %d/%d failed for %s: %s",
                            attempt, self.retries, path, exc)
                if attempt == self.retries:
                    return None
                time.sleep(self.delay * (2 ** attempt))
        return None

    def matchday(self, week):
        pp = self._page_props(f"/en-GB/laliga-easports/results?week={week}")
        if not pp:
            return []
        got = (pp.get("gameweek") or {}).get("week")
        # Guard the silent-ignore failure mode: if the site hands back a week
        # other than the one asked for, treat it as no data rather than
        # scraping the current matchday over and over under 38 labels.
        if got is not None and int(got) != int(week):
            log.warning("Asked for week %s, got %s - skipping", week, got)
            return []
        return pp.get("matches") or []

    def season_matches(self, weeks=38):
        out = []
        for w in range(1, weeks + 1):
            rows = self.matchday(w)
            if rows:
                out.extend(rows)
                log.info("  week %s: %d match(es)", w, len(rows))
        return out

    def match_stats(self, slug):
        """Both teams' full stat lines for one match."""
        pp = self._page_props(f"/en-GB/match/{slug}")
        if not pp:
            return None
        return pp.get("data") or pp.get("match") or pp


# LaLiga's snake_case -> this project's columns. The same Opta stats the
# Premier League feed provides, so this covers far more than the German one.
LL_STAT_MAP = {
    "possession":          "possession_percentage",
    "goals":               "goals",
    "shots":               "total_scoring_att",
    "shots_on_target":     "ontarget_scoring_att",
    "shots_off_target":    "shot_off_target",
    "shots_blocked":       "blocked_scoring_att",
    "shots_inside_box":    "att_ibox_target",
    "corners":             "won_corners",
    "crosses":             "total_cross",
    "crosses_accurate":    "accurate_cross",
    "pen_area_entries":    "pen_area_entries",
    "touches":             "touches",
    "passes":              "total_pass",
    "passes_accurate":     "accurate_pass",
    "tackles":             "total_tackle",
    "tackles_won":         "won_tackle",
    "interceptions":       "interception",
    "clearances":          "total_clearance",
    "saves":               "saves",
    "duels_won":           "duel_won",
    "aerials_won":         "aerial_won",
    "poss_won_att_third":  "poss_won_att_3rd",
    "poss_won_mid_third":  "poss_won_mid_3rd",
    "poss_won_def_third":  "poss_won_def_3rd",
    "poss_lost_all":       "poss_lost_all",
    "poss_lost_ctrl":      "poss_lost_ctrl",
    "fouls":               "fk_foul_lost",
    "yellows":             "total_yel_card",
    "reds":                "total_red_card",
    "offsides":            "total_offside",
    "dispossessed":        "dispossessed",
    "passes_final_third":  "total_final_third_passes",
    "passes_final_third_acc": "successful_final_third_passes",
    "goals_open_play":     "goals_openplay",
    "shots_open_play":     "att_openplay",
    "long_own_to_opp":     "long_pass_own_to_opp",
}

LL_AGAINST = {
    "possession_against": "possession_percentage",
    "shots_against":      "total_scoring_att",
    "shots_on_target_against": "ontarget_scoring_att",
    "goals_against":      "goals",
}


def _team(match, side):
    return match.get(f"{side}_team") or {}


def team_rows(match):
    rows = []
    for side in ("home", "away"):
        t = _team(match, side)
        if not t.get("id"):
            continue
        rows.append({
            "competition": COMPETITION,
            "team_id": qualify(t["id"]),
            "name": t.get("nickname") or t.get("name"),
            "short_name": t.get("boundname") or t.get("nickname"),
            "abbr": t.get("shortname"),
            "stadium": (match.get("venue") or {}).get("name"),
            "city": None, "capacity": None,
        })
    return rows


def match_row(match, season):
    finished = match.get("status") == "FullTime"
    home, away = _team(match, "home"), _team(match, "away")
    return {
        "competition": COMPETITION,
        "match_id": qualify(match["id"]),
        "season": str(season),
        "match_week": _week_of(match),
        "kickoff": (match.get("date") or match.get("time") or "")[:19].replace("T", " ") or None,
        "ground": (match.get("venue") or {}).get("name"),
        "period": "FullTime" if finished else "PreMatch",
        "home_team_id": qualify(home.get("id")),
        "away_team_id": qualify(away.get("id")),
        # Scores sit on the match, not inside the team blocks.
        "home_score": match.get("home_score") if finished else None,
        "away_score": match.get("away_score") if finished else None,
    }


def _week_of(match):
    """The matchday.

    The match page carries a `gameweek` block; the fixture listing does not, so
    the slug's trailing number is the fallback:
    "temporada-2026-2027-laliga-ea-sports-sevilla-fc-valencia-cf-5" -> 5
    """
    gw = match.get("gameweek")
    if isinstance(gw, dict) and gw.get("week"):
        return int(gw["week"])
    m = re.search(r"-(\d+)$", match.get("slug") or "")
    return int(m.group(1)) if m else None


def team_match_rows(match, season, stats):
    """One row per team. stats is the match page's `stats` block."""
    if not stats or not isinstance(stats, dict):
        return []
    blocks = {s: stats.get(s) for s in ("home", "away")}
    if not all(isinstance(b, dict) for b in blocks.values()):
        return []

    home, away = _team(match, "home"), _team(match, "away")
    if not (home.get("id") and away.get("id")):
        return []
    gf, ga = match.get("home_score"), match.get("away_score")
    if gf is None or ga is None:
        return []

    rows = []
    for side, t, o, is_home in (("home", home, away, 1), ("away", away, home, 0)):
        mine, theirs = (gf, ga) if is_home else (ga, gf)
        result = "W" if mine > theirs else ("L" if mine < theirs else "D")
        other = "away" if is_home else "home"
        row = {
            "competition": COMPETITION,
            "match_id": qualify(match["id"]),
            "team_id": qualify(t["id"]), "opponent_id": qualify(o["id"]),
            "is_home": is_home,
            "season": str(season),
            "match_week": _week_of(match),
            "kickoff": (match.get("date") or "")[:19].replace("T", " ") or None,
            "result": result,
            "points": 3 if result == "W" else (1 if result == "D" else 0),
            "goals": mine, "goals_against": theirs,
        }
        for col, key in LL_STAT_MAP.items():
            row[col] = blocks[side].get(key)
        for col, key in LL_AGAINST.items():
            row[col] = blocks[other].get(key)
        rows.append(row)
    return rows
