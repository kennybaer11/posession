"""Local web UI for the Premier League scraper.

    python app.py     ->  http://127.0.0.1:5000

Read-only. Every page is a thin wrapper over the views in views.sql; no
business logic lives here, so the UI can never disagree with the modelling
layer about what a number means.
"""

import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from flask import Flask, g, render_template, request, abort

load_dotenv()

app = Flask(__name__)


# -- database ---------------------------------------------------------------

def db():
    """One connection per request; Neon's pooled endpoint absorbs the churn."""
    if "conn" not in g:
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set - see .env.example")
        g.conn = psycopg.connect(dsn, row_factory=dict_row)
    return g.conn


@app.teardown_appcontext
def _close(_exc):
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()


def query(sql, params=None):
    with db().cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


# -- template helpers -------------------------------------------------------

@app.template_filter("num")
def _num(value, places=2):
    """Numerics arrive as Decimal with a long tail; show them like a human."""
    if value is None:
        return "-"
    try:
        return f"{float(value):.{places}f}"
    except (TypeError, ValueError):
        return value


@app.template_filter("pct")
def _pct(value):
    return "-" if value is None else f"{float(value):.1f}%"


@app.template_filter("dt")
def _dt(value, fmt="%d %b %Y"):
    return "-" if value is None else value.strftime(fmt)


@app.template_filter("signed")
def _signed(value, places=2):
    if value is None:
        return "-"
    return f"{float(value):+.{places}f}"


@app.template_filter("season")
def _season(value):
    """season is a text column holding the start year: 2025 -> 2025/26."""
    if value is None:
        return "-"
    try:
        start = int(value)
    except (TypeError, ValueError):
        return value
    return f"{start}/{(start + 1) % 100:02d}"


@app.context_processor
def _globals():
    return {"now": datetime.now(timezone.utc)}


# -- pages ------------------------------------------------------------------

@app.route("/")
def index():
    totals = one("""
        SELECT (SELECT count(*) FROM pl_teams)                         AS teams,
               (SELECT count(*) FROM pl_matches)                       AS matches,
               (SELECT count(*) FROM pl_matches WHERE kickoff > now()) AS fixtures,
               (SELECT count(*) FROM pl_team_match)                    AS stat_rows,
               (SELECT count(*) FROM pl_team_appearance)               AS appearances
    """)

    # Integrity checks worth surfacing: possession is zero-sum inside a match,
    # so a mean far from 50 means rows were dropped or paired wrongly.
    health = one("""
        SELECT count(*) FILTER (WHERE xg IS NULL)         AS missing_xg,
               count(*) FILTER (WHERE possession IS NULL) AS missing_poss,
               round(avg(possession)::numeric, 2)         AS avg_possession,
               round(min(xg)::numeric, 2)                 AS min_xg,
               round(max(xg)::numeric, 2)                 AS max_xg,
               round(avg(xg)::numeric, 2)                 AS avg_xg
        FROM pl_team_match
    """)

    # A match should contribute exactly two stat rows. Anything else is a bug.
    orphans = one("""
        SELECT count(*) AS n FROM (
            SELECT match_id FROM pl_team_match
            GROUP BY match_id HAVING count(*) <> 2
        ) x
    """)

    seasons = query("""
        SELECT season,
               count(*)                                 AS matches,
               count(*) FILTER (WHERE kickoff <= now()) AS played,
               min(kickoff)                             AS first_kickoff,
               max(kickoff)                             AS last_kickoff
        FROM pl_matches GROUP BY season ORDER BY season DESC
    """)

    coverage = query("""
        SELECT t.team_id, t.name, t.abbr, count(tm.match_id) AS matches,
               max(tm.kickoff) AS last_played
        FROM pl_teams t
        LEFT JOIN pl_team_match tm ON tm.team_id = t.team_id
        GROUP BY t.team_id, t.name, t.abbr
        ORDER BY matches ASC, t.name
    """)

    freshness = one("SELECT max(last_seen) AS last_scrape FROM pl_team_match")

    recent = query("""
        SELECT match_id, kickoff, season,
               max(team_name) FILTER (WHERE is_home = 1)     AS home,
               max(goals_for) FILTER (WHERE is_home = 1)     AS home_goals,
               max(xg_for)    FILTER (WHERE is_home = 1)     AS home_xg,
               max(team_name) FILTER (WHERE is_home = 0) AS away,
               max(goals_for) FILTER (WHERE is_home = 0) AS away_goals,
               max(xg_for)    FILTER (WHERE is_home = 0) AS away_xg
        FROM v_team_match
        GROUP BY match_id, kickoff, season
        ORDER BY kickoff DESC LIMIT 10
    """)

    return render_template("index.html", totals=totals, health=health,
                           orphans=orphans["n"], seasons=seasons,
                           coverage=coverage, freshness=freshness,
                           recent=recent)


@app.route("/teams")
def teams():
    rows = query("""
        SELECT f.*, t.name, t.abbr, t.short_name
        FROM v_team_form_current f
        JOIN pl_teams t ON t.team_id = f.team_id
        ORDER BY f.xg_diff_l5 DESC NULLS LAST
    """)
    return render_template("teams.html", rows=rows)


@app.route("/team/<team_id>")
def team(team_id):
    info = one("SELECT * FROM pl_teams WHERE team_id = %s", (team_id,))
    if not info:
        abort(404)
    form = one("SELECT * FROM v_team_form_current WHERE team_id = %s", (team_id,))
    matches = query(
        "SELECT * FROM v_team_match WHERE team_id = %s ORDER BY kickoff DESC",
        (team_id,))
    h2h = query("""
        SELECT h.*, o.name AS opponent_name, o.abbr AS opponent_abbr
        FROM v_h2h h JOIN pl_teams o ON o.team_id = h.opponent_id
        WHERE h.team_id = %s ORDER BY h.meetings DESC, o.name
    """, (team_id,))
    return render_template("team.html", info=info, form=form,
                           matches=matches, h2h=h2h)


@app.route("/matches")
def matches():
    season = request.args.get("season")   # text column, keep it text
    sql = """
        SELECT match_id, kickoff, season, match_week,
               max(team_name) FILTER (WHERE is_home = 1)      AS home,
               max(team_abbr) FILTER (WHERE is_home = 1)      AS home_abbr,
               max(goals_for) FILTER (WHERE is_home = 1)      AS home_goals,
               max(xg_for)    FILTER (WHERE is_home = 1)      AS home_xg,
               max(possession_for) FILTER (WHERE is_home = 1) AS home_poss,
               max(team_name) FILTER (WHERE is_home = 0)  AS away,
               max(team_abbr) FILTER (WHERE is_home = 0)  AS away_abbr,
               max(goals_for) FILTER (WHERE is_home = 0)  AS away_goals,
               max(xg_for)    FILTER (WHERE is_home = 0)  AS away_xg
        FROM v_team_match
        {where}
        GROUP BY match_id, kickoff, season, match_week
        ORDER BY kickoff DESC
    """
    if season:
        rows = query(sql.format(where="WHERE season = %s"), (season,))
    else:
        rows = query(sql.format(where=""))
    seasons = query("SELECT DISTINCT season FROM pl_matches ORDER BY season DESC")
    return render_template("matches.html", rows=rows, seasons=seasons,
                           current=season)


@app.route("/match/<match_id>")
def match(match_id):
    sides = query(
        "SELECT * FROM v_team_match WHERE match_id = %s ORDER BY is_home DESC",
        (match_id,))
    if len(sides) != 2:
        abort(404)
    home, away = sides
    state = {r["team_id"]: r for r in query(
        "SELECT * FROM v_match_game_state WHERE match_id = %s", (match_id,))}
    mid = {r["team_id"]: r for r in query(
        "SELECT * FROM v_team_midfield WHERE match_id = %s", (match_id,))}
    goals = query("""
        SELECT g.*, p.first_name, p.last_name, t.abbr
        FROM pl_match_goal g
        LEFT JOIN pl_player p ON p.player_id = g.player_id
        LEFT JOIN pl_teams t ON t.team_id = g.team_id
        WHERE g.match_id = %s ORDER BY g.minute
    """, (match_id,))
    # Rows rendered as a head-to-head comparison bar: (label, key, decimals).
    metrics = [
        ("Goals", "goals_for", 0), ("xG", "xg_for", 2),
        ("xG on target", "xgot_for", 2), ("Possession", "possession_for", 1),
        ("Shots", "shots_for", 0), ("On target", "shots_on_target_for", 0),
        ("Big chances", "big_chances_for", 0), ("Corners", "corners_for", 0),
        ("Passes", "passes", 0), ("Accurate passes", "passes_accurate", 0),
        ("Touches in opp box", "touches_opp_box", 0),
        ("Final third entries", "final_third_entries", 0),
        ("Tackles won", "tackles_won", 0), ("Interceptions", "interceptions", 0),
        ("Clearances", "clearances", 0), ("Saves", "saves", 0),
        ("Duels won", "duels_won", 0), ("Aerials won", "aerials_won", 0),
        ("Fouls", "fouls", 0), ("Yellows", "yellows", 0),
        ("Reds", "reds", 0), ("Offsides", "offsides", 0),
    ]
    return render_template("match.html", home=home, away=away, metrics=metrics,
                           state=state, mid=mid, goals=goals)


@app.route("/fixtures")
def fixtures():
    rows = query("SELECT * FROM v_fixture_features ORDER BY kickoff")
    return render_template("fixtures.html", rows=rows)


@app.route("/model")
def model():
    """Readiness of the modelling layer - no model is trained yet."""
    import load as loader

    train = loader.training_set(min_history=3)
    upcoming = loader.fixtures()
    feats = loader.feature_columns(train, upcoming)
    fit, holdout = loader.time_split(train)

    balance = (train["outcome"].value_counts().to_dict()
               if "outcome" in train and len(train) else {})

    # Group the feature list so the page reads as an inventory, not a dump.
    groups = {
        "Attacking form": [c for c in feats if "xg" in c and "xga" not in c
                           and "edge" not in c and "gap" not in c],
        "Defensive form": [c for c in feats if "xga" in c],
        "Points and results": [c for c in feats if "ppg" in c],
        "Volume": [c for c in feats if any(k in c for k in
                   ("shots", "sot", "corners", "poss"))],
        "Matchup edges": [c for c in feats if "edge" in c or "_vs_" in c],
        "Head to head": [c for c in feats if c.startswith("h2h")],
        "Schedule and fatigue": [c for c in feats if any(k in c for k in
                                ("rest", "last_14d", "european", "break"))],
    }
    seen = set().union(*groups.values()) if groups else set()
    groups["Other"] = [c for c in feats if c not in seen]
    groups = {k: v for k, v in groups.items() if v}

    coverage = None
    if len(train):
        coverage = {"first": train["kickoff"].min(),
                    "last": train["kickoff"].max()}

    return render_template(
        "model.html", n_train=len(train), n_fixtures=len(upcoming),
        n_features=len(feats), n_fit=len(fit), n_holdout=len(holdout),
        balance=balance, groups=groups, coverage=coverage,
        preview=upcoming.head(10).to_dict("records") if len(upcoming) else [])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
