"""Local web UI for the Premier League scraper.

    python app.py     ->  http://127.0.0.1:5000

Read-only. Every page is a thin wrapper over the views in views.sql; no
business logic lives here, so the UI can never disagree with the modelling
layer about what a number means.
"""

import os
import re
import secrets
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

load_dotenv()

import i18n
from i18n import _

app = Flask(__name__)
i18n.install(app)

# Sessions need a stable secret. A random one per process would log the admin
# out on every restart, so this is read from the environment and only falls
# back to a random value when unset - in which case the admin is unusable,
# which is the right failure: a predictable default secret is worse.
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(32)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024   # an odds sheet is tiny

ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")

# Hardening that only matters once this is reachable from the internet, and
# costs nothing locally. Set DEPLOYED=1 on the host.
DEPLOYED = os.getenv("DEPLOYED", "").lower() in ("1", "true", "yes")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,   # JavaScript cannot read the session
    SESSION_COOKIE_SAMESITE="Lax",  # not sent on cross-site POSTs
    # Only over HTTPS when deployed. Setting this locally would break the
    # session on plain-http://127.0.0.1, so it is conditional rather than
    # always-on.
    SESSION_COOKIE_SECURE=DEPLOYED,
)

app.config["DEPLOYED_SITE"] = DEPLOYED

if DEPLOYED:
    # Behind a host's proxy, Flask sees plain HTTP and would build http://
    # redirects and refuse to send a Secure cookie. This trusts the one proxy
    # in front of the app to report the real scheme.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# The site moved to betken.cz, which carries the tennis lines as well as the
# possession ones. Both domains reach this one app; once CANONICAL_HOST is set,
# a request on any other public domain is sent to the same path there,
# permanently. Left unset until betken.cz answers with a certificate, so a
# push cannot strand posession.cz visitors on a domain that does not work yet.
CANONICAL_HOST = "betken.cz"
OLD_HOSTS = ("posession.cz", "www.posession.cz", "www.betken.cz")


def site_name():
    """The domain to put in the brand and page titles."""
    if CANONICAL_HOST:
        return CANONICAL_HOST
    host = request.host.split(":")[0].lower() if request else ""
    return "betken.cz" if host.endswith("betken.cz") else "posession.cz"


@app.before_request
def _canonical_host():
    if not (DEPLOYED and CANONICAL_HOST):
        return None
    if request.host.split(":")[0].lower() in OLD_HOSTS:
        return redirect(f"https://{CANONICAL_HOST}{request.full_path.rstrip('?')}", code=301)
    return None

# Login throttling. A password exposed to the internet gets guessed at, and
# without a limit the only defence is password length. Keyed by IP, in memory:
# good enough for a single small instance, and it resets on restart, which is
# an acceptable trade for having no dependency.
_LOGIN_ATTEMPTS = {}
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 300


def _login_blocked(ip):
    now = time.time()
    hits = [t for t in _LOGIN_ATTEMPTS.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    _LOGIN_ATTEMPTS[ip] = hits
    return len(hits) >= LOGIN_MAX_ATTEMPTS


def _record_login_failure(ip):
    _LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


def admin_configured():
    return bool(ADMIN_USER and ADMIN_PASSWORD_HASH and os.getenv("SECRET_KEY"))


def login_required(view):
    """Gate a view behind the admin session.

    Fails closed: with no credentials configured the admin is unreachable
    rather than open. An unconfigured admin panel that anyone can use is a
    worse outcome than one that does not work.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not admin_configured():
            return render_template("admin_setup.html"), 503
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapper



def members_only(view):
    """Everything except the advice record sits behind the admin login on the
    public server. Locally (DEPLOYED unset) the pages stay open, so the app
    and the static build work without credentials."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not DEPLOYED:
            return view(*args, **kwargs)
        return login_required(view)(*args, **kwargs)
    return wrapper

# -- database ---------------------------------------------------------------

_pool = None


def _get_pool():
    """Connections kept open and reused, one pool per worker process.

    Opening a connection to Neon (Ohio) from the Prague server costs about a
    second of TLS and auth round trips - it was the floor under every page
    when each request opened its own. check_connection tests a connection
    before lending it, so one Neon closed while idle is replaced, not handed
    out broken.
    """
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set - see .env.example")
        _pool = ConnectionPool(dsn, min_size=1, max_size=6, max_idle=240,
                               kwargs={"row_factory": dict_row},
                               check=ConnectionPool.check_connection, open=True)
        import atexit
        atexit.register(_pool.close)
    return _pool


def db():
    """The request's connection, borrowed from the pool."""
    if "conn" not in g:
        g.conn = _get_pool().getconn()
    return g.conn


@app.teardown_appcontext
def _close(_exc):
    conn = g.pop("conn", None)
    if conn is not None:
        # putconn rolls back anything left open, so a read's transaction never
        # leaks into the next request.
        if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            conn.rollback()
        _get_pool().putconn(conn)


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
    return "-" if value is None else i18n.strftime(value, fmt)


@app.template_filter("signed")
def _signed(value, places=2):
    if value is None:
        return "-"
    return f"{float(value):+.{places}f}"


@app.template_filter("ago")
def _ago(value, now=None):
    """"in 2h 40m" / "18m ago", for a timezone-aware timestamp."""
    if not value:
        return "-"
    now = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    secs = (value - now).total_seconds()
    ahead, secs = secs > 0, abs(secs)
    if secs < 90:
        return _("just now")
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    mins = rem // 60
    part = (_("%(d)sd %(h)sh", d=d, h=h) if d else
            _("%(h)sh %(m)sm", h=h, m=mins) if h else _("%(m)sm", m=mins))
    return _("in %(t)s", t=part) if ahead else _("%(t)s ago", t=part)


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


def _code_version():
    """Short commit id of the running code, read once at startup - shown in
    the footer so anyone can see whether a push has gone live yet."""
    try:
        from advice import code_version
        return (code_version() or "")[:7]
    except Exception:
        return ""


CODE_VERSION = _code_version()


@app.context_processor
def _globals():
    return {"now": datetime.now(timezone.utc), "code_version": CODE_VERSION,
            "site_name": site_name()}



# -- leagues -----------------------------------------------------------------

LEAGUES = (("PL", "Premier League"), ("LaLiga", "LaLiga"),
           ("BL1", "Bundesliga"))
LEAGUE_NAMES = dict(LEAGUES)


def league():
    """The league being viewed. Defaults to the Premier League.

    Every page is scoped to one league rather than showing all three together:
    possession baselines differ between them, so a combined table would invite
    comparisons that are not like for like.
    """
    want = request.args.get("league", "PL")
    return want if want in LEAGUE_NAMES else "PL"


ALL = "all"


def scope():
    """The league scope for the Bets page, which alone may span all three.

    Every other page stays single-league on purpose: possession baselines
    differ between competitions, so a combined teams or matches table invites
    comparisons that are not like for like. A settled bet is different. It is
    just a bet, and the track record reads better whole than cut into three
    short pieces - especially while each piece is only a handful of rows.
    """
    return ALL if request.args.get("league") == ALL else league()


@app.context_processor
def _members():
    # Whether the full menu shows: always locally, only when signed in on the
    # public server.
    local = not DEPLOYED and not app.config.get("STATIC_EXPORT")
    return {"members": local or bool(session.get("admin")),
            # Which sport's categories the second menu row shows.
            "section": "tennis" if (request.endpoint or "").startswith("tennis") else "football"}


@app.context_processor
def _league_globals():
    return {"leagues": LEAGUES, "league": league(),
            "league_name": LEAGUE_NAMES.get(league(), league())}


# -- pages ------------------------------------------------------------------

@app.route("/overview")
@members_only
def index():
    lg = league()
    totals = one("""
        SELECT (SELECT count(*) FROM pl_teams WHERE competition = %(c)s) AS teams,
               (SELECT count(*) FROM pl_matches WHERE competition = %(c)s) AS matches,
               (SELECT count(*) FROM pl_matches
                 WHERE competition = %(c)s AND kickoff > now())          AS fixtures,
               (SELECT count(*) FROM pl_team_match WHERE competition = %(c)s) AS stat_rows,
               (SELECT count(*) FROM pl_team_appearance)                 AS appearances
    """, {"c": lg})

    # Integrity checks worth surfacing: possession is zero-sum inside a match,
    # so a mean far from 50 means rows were dropped or paired wrongly.
    health = one("""
        SELECT count(*) FILTER (WHERE xg IS NULL)         AS missing_xg,
               count(*) FILTER (WHERE possession IS NULL) AS missing_poss,
               round(avg(possession)::numeric, 2)         AS avg_possession,
               round(min(xg)::numeric, 2)                 AS min_xg,
               round(max(xg)::numeric, 2)                 AS max_xg,
               round(avg(xg)::numeric, 2)                 AS avg_xg
        FROM pl_team_match WHERE competition = %(c)s
    """, {"c": lg})

    # A match should contribute exactly two stat rows. Anything else is a bug.
    orphans = one("""
        SELECT count(*) AS n FROM (
            SELECT match_id FROM pl_team_match WHERE competition = %(c)s
            GROUP BY match_id HAVING count(*) <> 2
        ) x
    """, {"c": lg})

    seasons = query("""
        SELECT season,
               count(*)                                 AS matches,
               count(*) FILTER (WHERE kickoff <= now()) AS played,
               min(kickoff)                             AS first_kickoff,
               max(kickoff)                             AS last_kickoff
        FROM pl_matches WHERE competition = %(c)s
        GROUP BY season ORDER BY season DESC
    """, {"c": lg})

    coverage = query("""
        SELECT t.team_id, t.name, t.abbr, count(tm.match_id) AS matches,
               max(tm.kickoff) AS last_played
        FROM pl_teams t
        LEFT JOIN pl_team_match tm ON tm.team_id = t.team_id
        WHERE t.competition = %(c)s
        GROUP BY t.team_id, t.name, t.abbr
        ORDER BY matches ASC, t.name
    """, {"c": lg})

    freshness = one("SELECT max(last_seen) AS last_scrape FROM pl_team_match "
                    "WHERE competition = %(c)s", {"c": lg})

    recent = query("""
        SELECT match_id, kickoff, season,
               max(team_name) FILTER (WHERE is_home = 1)     AS home,
               max(goals_for) FILTER (WHERE is_home = 1)     AS home_goals,
               max(xg_for)    FILTER (WHERE is_home = 1)     AS home_xg,
               max(team_name) FILTER (WHERE is_home = 0) AS away,
               max(goals_for) FILTER (WHERE is_home = 0) AS away_goals,
               max(xg_for)    FILTER (WHERE is_home = 0) AS away_xg
        FROM v_team_match WHERE competition = %(c)s
        GROUP BY match_id, kickoff, season
        ORDER BY kickoff DESC LIMIT 10
    """, {"c": lg})

    return render_template("index.html", totals=totals, health=health,
                           orphans=orphans["n"], seasons=seasons,
                           coverage=coverage, freshness=freshness,
                           recent=recent)


@app.route("/teams")
@members_only
def teams():
    rows = query("""
        SELECT f.*, t.name, t.abbr, t.short_name
        FROM v_team_form_current f
        JOIN pl_teams t ON t.team_id = f.team_id
        WHERE t.competition = %(c)s
        ORDER BY f.possession_l5 DESC NULLS LAST
    """, {"c": league()})
    return render_template("teams.html", rows=rows)


@app.route("/team/<team_id>")
@members_only
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
@members_only
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
    lg = league()
    where = "WHERE competition = %(c)s"
    params = {"c": lg}
    if season:
        where += " AND season = %(s)s"
        params["s"] = season
    rows = query(sql.format(where=where), params)
    seasons = query("SELECT DISTINCT season FROM pl_matches WHERE competition = %(c)s "
                    "ORDER BY season DESC", {"c": lg})
    return render_template("matches.html", rows=rows, seasons=seasons,
                           current=season)


@app.route("/match/<match_id>")
@members_only
def match(match_id):
    sides = query(
        "SELECT * FROM v_team_match WHERE match_id = %s ORDER BY is_home DESC",
        (match_id,))
    if len(sides) != 2:
        # No stat line yet - an upcoming fixture that already has a betting
        # line recorded against it. Show what is known rather than 404ing a
        # page the Bets table links to.
        fixture = one("""
            SELECT m.match_id, m.kickoff, m.season, m.match_week, m.competition,
                   ht.name AS home_name, ht.abbr AS home_abbr,
                   at_.name AS away_name, at_.abbr AS away_abbr
            FROM pl_matches m
            JOIN pl_teams ht  ON ht.team_id = m.home_team_id
            JOIN pl_teams at_ ON at_.team_id = m.away_team_id
            WHERE m.match_id = %s""", (match_id,))
        if not fixture:
            abort(404)
        return render_template("match_pending.html", fixture=fixture)
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
    metrics = [(_(label), key, places) for label, key, places in metrics]
    return render_template("match.html", home=home, away=away, metrics=metrics,
                           state=state, mid=mid, goals=goals)


@app.route("/fixtures")
@members_only
def fixtures():
    # The combined view is horizon-limited where the per-league ones are not.
    # Both other leagues store a whole season of fixtures - 281 and 332 against
    # the Premier League's 21 - so "all leagues" unbounded is 634 rows of mostly
    # May. A fortnight is what the page is actually for: what is coming up that
    # might be worth a bet. The per-league tabs still hold the full list.
    want = scope()
    horizon = FIXTURE_HORIZON_DAYS if want == ALL else None
    rows = query(
        "SELECT * FROM v_fixture_features "
        " WHERE (%(c)s = 'all' OR competition = %(c)s)"
        "   AND (%(d)s::int IS NULL"
        "        OR kickoff <= now() + (%(d)s * INTERVAL '1 day'))"
        " ORDER BY kickoff", {"c": want, "d": horizon})

    # Whether a line has been recorded against each fixture, and what the model
    # makes of it. Taken from the same helper the Model and Bets pages use, so
    # the three cannot show different verdicts for one match.
    open_lines, graded = stake_guidance(want)
    open_lines = _explained(open_lines)
    by_match = {}
    for r in open_lines:
        by_match.setdefault(r["match_id"], []).append(r)

    rows = [dict(r, lines=by_match.get(r["match_id"], [])) for r in rows]
    return render_template("fixtures.html", rows=rows, graded=graded,
                           all_leagues=(want == ALL), scope=want,
                           league_names=LEAGUE_NAMES, horizon=horizon,
                           with_lines=sum(1 for r in rows if r["lines"]))


def settles_over(actual, line):
    """Does this figure settle as OVER at chance.cz?

    The boundary belongs to OVER, not UNDER. Their two sides read "Mene nez
    54,5" (less than 54.5) and "54,5 a vice" (54.5 AND MORE), so a figure
    landing exactly on the line is a winner for the over.

    Not a hypothetical: Arsenal returned exactly 54.5% against Chelsea on
    6 September 2026 with the line at 54.5, and chance.cz settled it as over.
    A strict > would have recorded that as a loss and quietly corrupted the
    record the whole model is being judged on.

    Possession is published to one decimal place, so an exact hit on a .5 line
    is rare but perfectly reachable.
    """
    return actual >= line


# How far ahead the all-leagues fixture view looks. Only that view: a league on
# its own shows its whole stored season.
FIXTURE_HORIZON_DAYS = 14


# The fit thresholds and sigma defaults live in calibration.py, which measures
# per-league sigma and must count rows exactly as the fit does. One source, so
# the readiness table, the predictor and the calibration cannot disagree.
from calibration import (MIN_FIT_ROWS, FIT_MIN_HISTORY, DEFAULT_SIGMA,  # noqa: E402
                         NAIVE_BIAS, NAIVE_SIGMA)
import calibration as calib  # noqa: E402


def league_status():
    """Per-league modelling readiness, for the all-leagues Model view.

    Counted in SQL rather than by loading each league's training frame: the
    page only needs to say which leagues are modelled and which are not, and
    three pandas loads plus three fits to answer that would double the cost of
    the slowest page on the site.
    """
    rows = {r["competition"]: r for r in query("""
        SELECT competition,
               count(*) FILTER (WHERE home_matches_before >= %(n)s
                                  AND away_matches_before >= %(n)s
                                  AND home_possession IS NOT NULL) AS train_rows,
               count(*) AS all_rows
        FROM v_match_features GROUP BY competition
    """, {"n": FIT_MIN_HISTORY})}
    lines = {r["competition"]: r for r in query("""
        SELECT m.competition,
               count(DISTINCT l.match_id) AS lines,
               count(DISTINCT l.match_id) FILTER (WHERE tm.possession IS NOT NULL) AS settled
        FROM pl_possession_line l
        JOIN pl_matches m ON m.match_id = l.match_id
        LEFT JOIN pl_team_match tm ON tm.match_id = l.match_id
                                  AND tm.team_id = l.team_id
        GROUP BY 1
    """)}
    cal = calib.stored(query)
    out = []
    for code, name in LEAGUES:
        n = (rows.get(code) or {}).get("train_rows") or 0
        out.append({
            "code": code, "name": name, "rows": n,
            "needed": MIN_FIT_ROWS,
            "fitted": n >= MIN_FIT_ROWS,
            "lines": (lines.get(code) or {}).get("lines") or 0,
            "settled": (lines.get(code) or {}).get("settled") or 0,
            "cal": cal.get(code),
        })
    return out


# Loaded frames per league, reused for a few minutes. Loading is the whole cost
# of a prediction - six to nine seconds for a league's training set and five for
# its fixtures once two seasons were stored, against about 0.01s per fit - and
# the Bets, Model and Fixtures pages each asked for the same frames again. A
# static build renders a dozen of those pages in one process, so without this
# it reloaded every league a dozen times. The data changes hourly at most, and
# ten minutes is well inside that.
_FRAME_TTL_SECONDS = 600
_frames = {}
_frames_lock = threading.Lock()
_refreshing = set()


def _cached(key, load):
    """load() once, then reuse; after the TTL, serve the old value and reload
    in the background.

    Stale-while-revalidate, so an expired entry never makes a visitor wait:
    only the very first load in a worker does, and warm_caches() does that at
    startup. A failed background reload keeps the old value and tries again on
    the next request.
    """
    hit = _frames.get(key)
    if hit is None:
        value = load()
        _frames[key] = (time.monotonic(), value)
        return value
    if time.monotonic() - hit[0] >= _FRAME_TTL_SECONDS:
        with _frames_lock:
            start = key not in _refreshing
            _refreshing.add(key)
        if start:
            def refresh():
                try:
                    _frames[key] = (time.monotonic(), load())
                except Exception:
                    app.logger.exception("background reload of %s failed", key)
                finally:
                    with _frames_lock:
                        _refreshing.discard(key)
            threading.Thread(target=refresh, daemon=True).start()
    return hit[1]


def _league_frames(competition):
    import load as loader
    return _cached(("frames", competition), lambda: (
        loader.training_set(season="all", competition=competition,
                            min_history=FIT_MIN_HISTORY),
        loader.fixtures(competition=competition)))


def _model_frames(competition):
    """The Model page's own view: the configured season and history rule."""
    import load as loader
    return _cached(("model", competition), lambda: (
        loader.training_set(competition=competition),
        loader.fixtures(competition=competition)))


def warm_caches():
    """Load every league's frames in the background when a worker starts, so
    the first visitor after a deploy or restart does not pay for it."""
    def run():
        for code, _ in LEAGUES:
            for fn in (_league_frames, _model_frames):
                try:
                    fn(code)
                except Exception:
                    app.logger.exception("cache warm-up for %s failed", code)
    threading.Thread(target=run, daemon=True).start()


def _fitted_predictor(competition, settled_ids=()):
    """Fit the model for this league and return match_id -> prediction.

    Fitted per request rather than cached: 300-odd rows and ten columns costs
    milliseconds, and a stale model that silently disagrees with the Model page
    would cost far more than that to notice.

    Upcoming fixtures are predicted by the model fitted on everything played.
    A PLAYED match must never be: that model has already seen its result. The
    Bets page used to grade settled lines exactly that way, and hindsight made
    the record look far better than any bet placed at the time could have been.
    So each match in settled_ids gets its own fit on the matches that kicked off
    BEFORE it - the prediction the site would actually have shown - and none if
    that earlier history was too short to fit, in which case the row falls back
    to the naive midpoint like any other unfittable prediction.

    Returns None when the league has too little history to fit, which is a real
    state early in a season rather than an error.
    """
    try:
        import load as loader
        import model as m
        train, upcoming = _league_frames(competition)
        feats = m.available_features(train)
        if len(train) < MIN_FIT_ROWS or not feats or not len(upcoming):
            return None
        fitted = m.build(alpha=1.0)
        fitted.fit(train[feats], train[loader.TARGET],
                   ridge__sample_weight=train["weight"])
        preds = dict(zip(upcoming["match_id"].astype(str),
                         fitted.predict(upcoming[feats])))
        # Fixtures whose 1X2 odds are not out yet: predicted without them.
        odds_cols = [c for c in m.ODDS_FEATURES if c in feats]
        if odds_cols:
            missing = upcoming[upcoming[odds_cols].isna().any(axis=1)]
            base = [c for c in feats if c not in odds_cols]
            if len(missing) and base:
                plain = m.build(alpha=1.0)
                plain.fit(train[base], train[loader.TARGET],
                          ridge__sample_weight=train["weight"])
                preds.update(zip(missing["match_id"].astype(str),
                                 plain.predict(missing[base])))

        # Settled lines: one out-of-sample fit each, on strictly earlier matches.
        wanted = {str(x) for x in settled_ids}
        ids = train["match_id"].astype(str)
        for i in train.index[ids.isin(wanted)]:
            earlier = train[train["kickoff"] < train.at[i, "kickoff"]]
            if len(earlier) < MIN_FIT_ROWS:
                continue
            past = m.build(alpha=1.0)
            past.fit(earlier[feats], earlier[loader.TARGET],
                     ridge__sample_weight=earlier["weight"])
            preds[str(train.at[i, "match_id"])] = float(
                past.predict(train.loc[[i], feats])[0])
        return lambda mid: preds.get(str(mid))
    except Exception:
        return None


def _line_rows(want=None):
    """Every recorded line with the model's view of it, settled or not.

    want is a competition code, or ALL to span every league.
    """
    from scipy.stats import norm
    import model as m

    want = want or league()

    # Ridge on the ten possession columns at a 90-day half-life, measured over
    # 322 walk-forward matches. The naive midpoint's 0.98 bias and 8.40 sigma
    # belonged to a model that only looked better because a 30-day half-life
    # had cut the training set to an effective 28 rows.
    #
    # NAIVE_* is the fallback for a league with too little history to fit
    # anything, which is Bundesliga's situation for another few matchdays.
    # Per league: the measured width of that league's own prediction errors,
    # or the default where a league has too little history to measure.
    sigmas = {c: float(r["sigma"]) for c, r in calib.stored(query).items()}
    comps = ([c for c, _ in LEAGUES] if want == ALL else [want])
    # One line per match. When the market moves, a second line for the same
    # match gets recorded (Dortmund at 57.0, then 58.0 a day later), and grading
    # both counted one bet twice. The FIRST line recorded is kept: it is the
    # price the scraper exists to capture, and with --skip-priced a fixture is
    # never re-scraped once priced, so first-seen is what every future record
    # will hold anyway. Later lines stay in the table as line-movement history.
    rows = query("""
        SELECT * FROM (
            SELECT DISTINCT ON (l.match_id, l.bookmaker)
                   l.line, l.over_odds, l.under_odds, l.captured_at,
                   t.name AS team, l.team_id,
                   m.match_id, m.kickoff, m.competition, ht.abbr AS home_abbr,
                   at_.abbr AS away_abbr, m.home_team_id,
                   ht.name AS home_name, at_.name AS away_name,
                   f.poss_naive_l5 AS naive,
                   tm.possession AS actual
            FROM pl_possession_line l
            JOIN pl_teams t   ON t.team_id = l.team_id
            JOIN pl_matches m ON m.match_id = l.match_id
            JOIN pl_teams ht  ON ht.team_id = m.home_team_id
            JOIN pl_teams at_ ON at_.team_id = m.away_team_id
            LEFT JOIN v_match_features f ON f.match_id = l.match_id
            LEFT JOIN pl_team_match tm ON tm.match_id = l.match_id
                                      AND tm.team_id = l.team_id
            WHERE m.competition = ANY(%(cs)s)
              -- A postponed match voids the line that was priced for the old
              -- date: Levante v Athletic was suspended on 16 Sep 2026 and
              -- rescheduled to 21 Oct, and its September line hung around as
              -- an upcoming tip. pl_advice keeps the kickoff the advice was
              -- given for, so a mismatch with the fixture's kickoff is the
              -- postponement. The new date gets a new market, and a new line.
              AND NOT EXISTS (SELECT 1 FROM pl_advice a
                              WHERE a.match_id = l.match_id
                                AND a.kickoff <> m.kickoff)
            ORDER BY l.match_id, l.bookmaker, l.captured_at ASC NULLS LAST, l.line
        ) first_lines
        ORDER BY kickoff DESC
    """, {"cs": comps})

    # One fit per league in scope, plus an out-of-sample fit per settled line.
    # A league with too little history returns None and its rows fall back to
    # the midpoint - which the rows say.
    settled = {}
    for r in rows:
        if r["actual"] is not None:
            settled.setdefault(r["competition"], set()).add(r["match_id"])
    predictors = {c: _fitted_predictor(c, settled.get(c, ())) for c in comps}
    fixture_naive = {r["match_id"]: r["poss_naive_l5"] for r in query(
        "SELECT match_id, poss_naive_l5 FROM v_fixture_features "
        "WHERE competition = ANY(%(cs)s)", {"cs": comps})}

    # Grade first, so the stake ratings below know how much evidence exists.
    # Counted per league, not across the scope: a rating is a claim about this
    # model in this competition, and pooling three leagues' settled bets would
    # let the Premier League's record vouch for a Bundesliga prediction.
    graded_by = {}
    for r in rows:
        if r["actual"] is not None:
            graded_by[r["competition"]] = graded_by.get(r["competition"], 0) + 1
    graded = sum(1 for r in rows if r["actual"] is not None)

    out = []
    for r in rows:
        naive = r["naive"] if r["naive"] is not None             else fixture_naive.get(r["match_id"])
        over_odds = float(r["over_odds"]) if r["over_odds"] else None
        under_odds = float(r["under_odds"]) if r["under_odds"] else None
        line = float(r["line"])

        pred = p_over = None
        side = None
        p_side = edge = None
        rating, why = 0, "no prediction available"
        book_over = margin = None
        predictor = predictors.get(r["competition"])
        graded_here = graded_by.get(r["competition"], 0)
        fallback = False

        if naive is not None:
            # The fitted model where one exists, the midpoint plus its own
            # bias where it does not. Mixing the two - a ridge bias applied to
            # a midpoint estimate - would be a number with no meaning.
            home_pred = (predictor(r["match_id"]) if predictor else None)
            if home_pred is None:
                home_pred = float(naive) + NAIVE_BIAS
                sigma = NAIVE_SIGMA
                fallback = True
            else:
                sigma = sigmas.get(r["competition"], DEFAULT_SIGMA)
            pred = home_pred if r["team_id"] == r["home_team_id"]                 else 100 - home_pred
            p_over = float(1 - norm.cdf(line, pred, sigma))
            side, p_side, edge, rating, why = m.choose_side(
                p_over, over_odds, under_odds, graded_here)

        # With both prices we can strip the margin out and see what the
        # bookmaker actually thinks, rather than what the price alone implies.
        if over_odds and under_odds:
            book_over, _, margin = m.devig(over_odds, under_odds)

        actual = float(r["actual"]) if r["actual"] is not None else None
        hit = None
        if actual is not None and side:
            hit = settles_over(actual, line) if side == "OVER" \
                else not settles_over(actual, line)

        out.append({**r, "side": side, "over_odds": over_odds,
                    "under_odds": under_odds, "odds": (
                        over_odds if side == "OVER" else
                        under_odds if side == "UNDER" else None),
                    "line": line, "pred": pred, "p_over": p_over,
                    "p_side": p_side, "edge": edge, "actual": actual,
                    "hit": hit, "backed": bool(side) and (edge or 0) > 0,
                    "rating": rating, "why": why, "fallback": fallback,
                    "sigma": sigma if naive is not None else None,
                    "book_over": book_over, "margin": margin})
    return out, graded


def vs_bookmaker(rows):
    """How close the model's prediction and the bookmaker's line each came to
    the actual possession, over every settled line - per league and overall.

    The honest scoreboard for the whole project. A model whose predictions are
    no closer than the line has no edge whatever the stake guidance says: any
    gap between the two is then its own error, not the bookmaker's.
    """
    settled = [r for r in rows
               if r["actual"] is not None and r["pred"] is not None]

    def summary(sub):
        if not sub:
            return None
        n = len(sub)
        model_err = [abs(r["pred"] - r["actual"]) for r in sub]
        line_err = [abs(r["line"] - r["actual"]) for r in sub]
        return {"n": n, "model": sum(model_err) / n, "line": sum(line_err) / n,
                "closer": sum(1 for a, b in zip(model_err, line_err) if a < b)}

    def information(sub):
        """actual - line = a + b * (pred - line), fitted by least squares.

        b is how much of the model's disagreement with the line comes true:
        0 means the model knows nothing the bookmaker does not, 1 that the
        line is off by as much as the model says. Measured 19 Sep 2026 on 51
        lines at 0.42 +- 0.32 - undecided; ~230 lines should settle it.
        """
        if len(sub) < 10:
            return None
        import numpy as np
        x = np.array([r["pred"] - r["line"] for r in sub], dtype=float)
        y = np.array([r["actual"] - r["line"] for r in sub], dtype=float)
        X = np.column_stack([np.ones(len(x)), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        cov = (resid @ resid / (len(x) - 2)) * np.linalg.inv(X.T @ X)
        b, se = float(beta[1]), float(np.sqrt(cov[1, 1]))
        return {"b": b, "se": se, "lo": b - 1.96 * se, "hi": b + 1.96 * se}

    out = []
    for code, name in LEAGUES:
        sub = [r for r in settled if r["competition"] == code]
        out.append(dict(code=code, name=name, info=information(sub),
                        **(summary(sub) or {"n": 0})))
    total = summary(settled)
    if total:
        total["info"] = information(settled)
    return out, total


def stake_guidance(want=None, with_rows=False):
    """Lines on matches that have not been played yet."""
    rows, graded = _line_rows(want)
    open_lines = [r for r in rows if r["actual"] is None]
    open_lines.sort(key=lambda r: (-r["rating"],
                                   -(r["edge"] if r["edge"] is not None else -9)))
    return (open_lines, graded, rows) if with_rows else (open_lines, graded)


# model.choose_side and model.verdict explain themselves in English, and that
# English is also what advice.py freezes into pl_advice - so it is translated
# here, on the way to a page, never where it is made. Each pattern is one of
# the fixed sentences model.py builds; its numbers are carried over as-is.
_NUM = r"(?P<{}>[-+]?[\d.]+%?)"
_EXPLAIN = [(re.compile(p.format(**{k: _NUM.format(k) for k in (
                "odds", "gap", "be", "score", "cap", "n", "edge", "w", "rate",
                "z", "k")}) + "$"), msgid) for p, msgid in (
    (r"best side is (?P<side>OVER|UNDER) at {odds}, still {gap} short of its "
     r"{be} breakeven",
     "best side is %(side)s at %(odds)s, still %(gap)s short of its %(be)s "
     "breakeven"),
    (r"edge alone suggests {score}/10, capped at {cap} by (?P<label>.+) "
     r"\({n} settled\)",
     "edge alone suggests %(score)s/10, capped at %(cap)s %(by)s (%(n)s settled)"),
    (r"edge of {edge} at {odds}", "edge of %(edge)s at %(odds)s"),
    (r"{w}/{n} at {rate} against a {be} breakeven - {z} standard errors clear, "
     r"which luck does not explain",
     "%(w)s/%(n)s at %(rate)s against a %(be)s breakeven - %(z)s standard "
     "errors clear, which luck does not explain"),
    (r"{w}/{n} at {rate}, below the {be} breakeven - the model is losing to "
     r"the price",
     "%(w)s/%(n)s at %(rate)s, below the %(be)s breakeven - the model is "
     "losing to the price"),
    (r"{w}/{n} at {rate} against {be} breakeven, but only {z} standard errors "
     r"clear; about {k} settled bets at this rate would settle it",
     "%(w)s/%(n)s at %(rate)s against %(be)s breakeven, but only %(z)s "
     "standard errors clear; about %(k)s settled bets at this rate would "
     "settle it"),
    (r"{w}/{n} at {rate} against {be} breakeven, but only {z} standard errors "
     r"clear",
     "%(w)s/%(n)s at %(rate)s against %(be)s breakeven, but only %(z)s "
     "standard errors clear"),
)]
_ONLY_N = re.compile(r"only (\d+) settled bets?\. Below about 50 the result is "
                     r"noise whichever way it falls$")


def explain(text):
    """A stake or verdict explanation from model.py, in the page's language."""
    if not text:
        return text
    m = _ONLY_N.match(text)
    if m:
        return i18n.ngettext(
            "only %(num)s settled bet. Below about 50 the result is noise "
            "whichever way it falls",
            "only %(num)s settled bets. Below about 50 the result is noise "
            "whichever way it falls", int(m.group(1)))
    for pattern, msgid in _EXPLAIN:
        m = pattern.match(text)
        if m:
            params = m.groupdict()
            if "side" in params:
                params["side"] = _(params["side"])
            if "label" in params:
                params["by"] = _("by " + params.pop("label"))
            return _(msgid, **params)
    return _(text)


def _explained(rows):
    """Copies of line rows with `why` in the page's language, for display."""
    return [dict(r, why=explain(r["why"])) for r in rows]


# -- scraper status ---------------------------------------------------------

WORKFLOW = Path(__file__).resolve().parent / ".github" / "workflows" / "odds.yml"


def next_scrapes(n=4, now=None):
    """When the odds workflow is next due, read from its own cron lines.

    Parsed from the workflow rather than restated here. A schedule written in
    two places drifts, and a status page that confidently names a time nothing
    runs at is worse than one that says nothing.

    GitHub's scheduler is best-effort - runs are routinely minutes late and can
    be dropped under load - so these are "due at", not "will run at".
    """
    import re
    from datetime import date, time as _time, timedelta
    try:
        text = WORKFLOW.read_text(encoding="utf-8")
    except OSError:
        return []
    slots = sorted({(int(h), int(m)) for m, h in
                    re.findall(r'cron:\s*"(\d+)\s+(\d+)\s+\*\s+\*\s+\*"', text)})
    if not slots:
        return []
    now = now or datetime.now(timezone.utc)
    out = []
    for day in range(3):
        d = now.date() + timedelta(days=day)
        for h, mi in slots:
            when = datetime.combine(d, _time(h, mi), tzinfo=timezone.utc)
            if when > now:
                out.append(when)
    return sorted(out)[:n]


@app.route("/status")
@members_only
def status():
    """What the odds scraper has been doing, and whether it worked.

    The question this answers is not "did webscraper.io run" - their dashboard
    shows that - but "did anything reach the database". A job can finish
    perfectly and still store nothing, because the market was not offered or
    the slug matched no fixture, and only this side knows which.
    """
    runs = query("""
        SELECT * FROM pl_scrape_run ORDER BY started_at DESC LIMIT 25
    """)
    last = runs[0] if runs else None

    coverage = query("""
        SELECT m.competition,
               count(*) AS fixtures,
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM pl_possession_line l
                   WHERE l.match_id = m.match_id)) AS priced
        FROM pl_matches m
        WHERE m.kickoff BETWEEN now() AND now() + INTERVAL '72 hours'
        GROUP BY 1 ORDER BY 1
    """)
    # Parked fixtures are shown as parked. A throttle that quietly stops
    # scraping things is indistinguishable from a scraper that has broken.
    import odds_pipeline as op
    unpriced = query("""
        SELECT m.kickoff, m.competition, ht.name AS home, at_.name AS away,
               COALESCE(a.attempts, 0) AS attempts,
               a.last_attempt,
               (COALESCE(a.attempts, 0) >= %(max)s
                AND m.kickoff > now() + (%(near)s * INTERVAL '1 hour')
                AND a.last_attempt >= now() - """ + op.recheck_sql() + """) AS parked,
               LEAST(a.last_attempt + """ + op.recheck_sql() + """,
                     m.kickoff - (%(near)s * INTERVAL '1 hour')) AS next_read
        FROM pl_matches m
        JOIN pl_teams ht  ON ht.team_id = m.home_team_id
        JOIN pl_teams at_ ON at_.team_id = m.away_team_id
        LEFT JOIN pl_odds_attempt a ON a.match_id = m.match_id
        WHERE m.kickoff BETWEEN now() AND now() + INTERVAL '72 hours'
          AND NOT EXISTS (SELECT 1 FROM pl_possession_line l
                          WHERE l.match_id = m.match_id)
        ORDER BY m.kickoff
    """, {"max": op.MAX_EMPTY_ATTEMPTS, "near": op.ALWAYS_RETRY_WITHIN_HOURS,
          "recheck": op.PARKED_RECHECK_HOURS})

    # A run started by the runner proves the schedule is armed - that the
    # secret is present and the cron fired. Nothing else on this page can.
    ci_runs = [r for r in runs if r["source"] == "github-actions"]
    return render_template(
        "status.html", runs=runs, last=last, coverage=coverage,
        unpriced=unpriced, upcoming=next_scrapes(),
        max_attempts=op.MAX_EMPTY_ATTEMPTS,
        retry_within=op.ALWAYS_RETRY_WITHIN_HOURS,
        recheck_hours=op.PARKED_RECHECK_HOURS,
        parked_n=sum(1 for r in unpriced if r["parked"]),
        ci_runs=len(ci_runs), last_ci=(ci_runs[0] if ci_runs else None),
        now=datetime.now(timezone.utc),
        totals={"fixtures": sum(c["fixtures"] for c in coverage),
                "priced": sum(c["priced"] for c in coverage)})


@app.route("/bets")
@members_only
def bets():
    """Every recorded line, what the model said, and how it settled.

    The point of this page is to build a track record before any money is
    staked on one. A model's own edge estimate is a claim about itself; this
    is the only thing that can check it.
    """
    want = scope()
    rows, graded = _line_rows(want)

    staked = returned = 0.0
    settled = won = 0
    for r in rows:
        if r["actual"] is None:
            continue
        settled += 1
        won += bool(r["hit"])
        if r["backed"] and r["odds"]:
            staked += 1
            returned += r["odds"] if r["hit"] else 0.0

    import model as m
    graded_bets = [(bool(r["hit"]), r["odds"]) for r in rows
                   if r["actual"] is not None and r["backed"] and r["odds"]]
    call = m.verdict(graded_bets)
    call = dict(call, reason=explain(call["reason"]))
    rows = _explained(rows)

    totals = {
        "recorded": len(rows), "settled": settled, "won": won,
        "staked": staked, "returned": returned,
        "pnl": returned - staked,
        "roi": (returned - staked) / staked if staked else None,
        "both_prices": sum(1 for r in rows
                           if r["over_odds"] and r["under_odds"]),
    }
    return render_template("bets.html", rows=rows, totals=totals,
                           verdict=call, calibrations=calib.stored(query),
                           default_sigma=DEFAULT_SIGMA,
                           scope=want, all_leagues=(want == ALL),
                           league_names=LEAGUE_NAMES,
                           fallback_n=sum(1 for r in rows if r["fallback"]))


@app.route("/model")
@members_only
def model():
    """Readiness of the modelling layer - no model is trained yet."""
    import load as loader

    # All-leagues is a different page, not a wider version of this one. The
    # training set, the feature inventory and the baselines are each about one
    # league's own data, and stacking three leagues' rows into them would
    # describe a model that does not exist. What DOES span leagues is the stake
    # guidance and the question of which leagues are modelled at all, so that
    # is what the combined view shows.
    want = scope()
    if want == ALL:
        open_lines, graded, all_rows = stake_guidance(ALL, with_rows=True)
        vs_leagues, vs_total = vs_bookmaker(all_rows)
        open_lines = _explained(open_lines)
        return render_template(
            "model.html", all_leagues=True, scope=ALL,
            vs_leagues=vs_leagues, vs_total=vs_total,
            statuses=league_status(), open_lines=open_lines, graded=graded,
            default_sigma=DEFAULT_SIGMA,
            fallback_n=sum(1 for r in open_lines if r["fallback"]),
            league_names=LEAGUE_NAMES,
            n_train=0, n_features=0, n_fit=0, n_holdout=0, n_fixtures=0,
            baselines=None, stats=None, coverage=None, shortfall=None,
            sparse=None, groups={}, speculative=False, preview=[])

    lg = league()
    train, upcoming = _model_frames(lg)
    feats = loader.feature_columns(train, upcoming)

    # A league early in its season has no training rows at all: min_history
    # asks for prior matches nobody has played yet. Show what the model WOULD
    # use, derived from the fixture side, rather than rendering an empty page
    # that looks broken.
    speculative = False
    if not feats and len(upcoming):
        feats = loader.feature_columns(upcoming, upcoming)
        speculative = bool(feats)

    shortfall = None
    if not len(train):
        played = one("""SELECT count(*) AS n FROM pl_matches
                        WHERE competition = %(c)s AND period = 'FullTime'""",
                     {"c": lg})["n"]
        cfg = loader.training_config()
        shortfall = {"played": played, "min_history": cfg["min_history"],
                     "season": cfg["season"]}
    fit, holdout = loader.time_split(train)
    target = loader.TARGET

    stats = None
    if len(train):
        y = train[target]
        stats = {"mean": y.mean(), "min": y.min(), "max": y.max(),
                 "std": y.std()}

    # Group the feature list so the page reads as an inventory, not a dump.
    # Possession inputs lead, because that is what is being predicted.
    groups = {
        "Possession": [c for c in feats if "poss" in c or "pass" in c
                       or "touch" in c or "long_balls" in c
                       or "dispossessed" in c or "recoveries" in c],
        "Attacking form": [c for c in feats if "xg" in c and "xga" not in c
                           and "edge" not in c and "gap" not in c],
        "Defensive form": [c for c in feats if "xga" in c],
        "Points and results": [c for c in feats if "ppg" in c],
        "Volume": [c for c in feats if any(k in c for k in
                   ("shots", "sot", "corners"))],
        "Matchup edges": [c for c in feats if "edge" in c or "_vs_" in c],
        "Head to head": [c for c in feats if c.startswith("h2h")],
        "Schedule and fatigue": [c for c in feats if any(k in c for k in
                                ("rest", "last_14d", "european", "break"))],
    }
    ordered, seen = {}, set()
    for name, cols in groups.items():
        cols = [c for c in cols if c not in seen]
        seen.update(cols)
        if cols:
            ordered[_(name)] = cols
    rest = [c for c in feats if c not in seen]
    if rest:
        ordered[_("Other")] = rest

    coverage = None
    if len(train):
        coverage = {"first": train["kickoff"].min(),
                    "last": train["kickoff"].max()}

    # Open lines, with a stake rating. Kept on this page because it is the
    # model's own recommendation; the Bets page is the record of how such
    # recommendations turned out.
    open_lines, graded = stake_guidance(lg)
    open_lines = _explained(open_lines)

    # How much of the training set each h2h column actually covers - in a
    # single season most pairs have not met yet, so these are mostly empty.
    sparse = []
    for c in feats:
        if len(train) and train[c].notna().sum() < len(train) * 0.5:
            sparse.append((c, int(train[c].notna().sum())))

    return render_template(
        "model.html", target=target, n_train=len(train),
        n_fixtures=len(upcoming), n_features=len(feats), n_fit=len(fit),
        n_holdout=len(holdout), stats=stats, groups=ordered, coverage=coverage,
        baselines=loader.baselines(train), sparse=sparse,
        open_lines=open_lines, graded=graded,
        all_leagues=False, scope=lg, statuses=None,
        league_names=LEAGUE_NAMES,
        fallback_n=sum(1 for r in open_lines if r["fallback"]),
        speculative=speculative, shortfall=shortfall,
        preview=upcoming.head(10).to_dict("records") if len(upcoming) else [])


# -- admin -------------------------------------------------------------------
#
# Deliberately NOT part of the published site. export_static.py renders a fixed
# list of routes, and these are not on it, so nothing under /admin is ever
# written into the static build - the Pages site stays a read-only snapshot
# with no login form on it to attack.

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not admin_configured():
        return render_template("admin_setup.html"), 503
    error = None
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    ip = ip.split(",")[0].strip()

    if request.method == "POST":
        if _login_blocked(ip):
            return render_template(
                "admin_login.html",
                error=_("Too many attempts. Wait five minutes.")), 429

        user = request.form.get("username", "")
        password = request.form.get("password", "")
        if user == ADMIN_USER and check_password_hash(ADMIN_PASSWORD_HASH,
                                                      password):
            session["admin"] = user
            session.permanent = False
            target = request.args.get("next") or url_for("admin")
            # Only ever redirect within this app: an attacker-supplied ?next=
            # pointing elsewhere would turn the login into an open redirect.
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("admin")
            _LOGIN_ATTEMPTS.pop(ip, None)
            return redirect(target)
        _record_login_failure(ip)
        # One message for both cases: saying which was wrong tells an attacker
        # whether the username exists.
        error = _("Wrong username or password.")
    return render_template("admin_login.html", error=error)


# Registered "/admin/advice" first so url_for() builds "/": the decorator
# nearest the function is added first, and url_for uses the first rule.
@app.route("/admin/advice")
@app.route("/")
def admin_advice():
    """The advice the site gave, frozen at kickoff, and how it settled.

    Nothing here is recomputed. Side, odds, edge and stake come from pl_advice
    as they stood when the match kicked off; only the actual possession is
    looked up, because that is a fact about the match rather than a judgement.
    Changing the model changes the Learning page, never this one.
    """
    import model as m
    rows = query("""
        SELECT a.*, t.name AS team, ht.abbr AS home_abbr, at_.abbr AS away_abbr,
               tm.possession AS actual, m.kickoff AS fixture_kickoff,
               (m.kickoff <> a.kickoff) AS postponed
        FROM pl_advice a
        JOIN pl_matches m ON m.match_id = a.match_id
        JOIN pl_teams t   ON t.team_id = a.team_id
        JOIN pl_teams ht  ON ht.team_id = m.home_team_id
        JOIN pl_teams at_ ON at_.team_id = m.away_team_id
        LEFT JOIN pl_team_match tm ON tm.match_id = a.match_id
                                  AND tm.team_id = a.team_id
        ORDER BY a.kickoff DESC
    """)
    settled, pending, postponed = [], [], []
    for r in rows:
        r = dict(r)
        for k in ("line", "odds", "edge", "pred", "p_over", "sigma", "actual"):
            r[k] = float(r[k]) if r[k] is not None else None
        if r["postponed"]:
            # The match moved after this advice was given, so the bet was void.
            # Not settled, not pending - just history, and only for the admin.
            postponed.append(r)
            continue
        if r["actual"] is None:
            pending.append(r)
            continue
        r["hit"] = (None if not r["side"] else
                    settles_over(r["actual"], r["line"]) if r["side"] == "OVER"
                    else not settles_over(r["actual"], r["line"]))
        settled.append(r)

    bets = [r for r in settled if r["backed"] and r["odds"]]
    won = sum(1 for r in bets if r["hit"])
    returned = sum(r["odds"] for r in bets if r["hit"])
    # Also at the advised stake: rating N is N tenths of the 10/10 stake, so a
    # 1/10 bet risks 0.1 units. This is what following the advice to the letter
    # would have made, rather than betting every recommendation the same.
    staked_r = sum((r["rating"] or 0) / 10 for r in bets)
    returned_r = sum((r["rating"] or 0) / 10 * r["odds"] for r in bets if r["hit"])
    totals = {
        "advised": len(settled), "bets": len(bets), "won": won,
        "pnl": returned - len(bets),
        "roi": (returned - len(bets)) / len(bets) if bets else None,
        "staked_r": staked_r, "pnl_r": returned_r - staked_r,
        "roi_r": (returned_r - staked_r) / staked_r if staked_r else None,
        "no_bet": sum(1 for r in settled if not r["backed"]),
    }
    call = m.verdict([(bool(r["hit"]), r["odds"]) for r in bets])
    # Visitors see the bets only; "no bet" lines stay visible to the admin.
    # The totals already count advised bets alone, so they do not change.
    if not session.get("admin"):
        settled = [r for r in settled if r["backed"]]
        pending = [r for r in pending if r["backed"]]
        postponed = []
    return render_template("admin_advice.html", settled=settled,
                           pending=pending, postponed=postponed,
                           totals=totals, verdict=call,
                           league_names=LEAGUE_NAMES, user=session.get("admin"))


# Bookmakers whose lines the aces project collects, as they are labelled here.
TENNIS_BOOKS = {"betano": "Betano", "chance": "Chance", "manual": "Manual"}


@app.route("/tennis")
def tennis():
    """Ace and double-fault lines, priced by the aces project.

    The rows are aces.line, written by aces/odds.py (Betano), load_chance.py
    (Chance.cz) or price.py (typed by hand), and settled by its daily refresh.
    ?book=betano|chance shows one bookmaker; the totals follow the filter. As with the possession advice, nothing is
    recomputed here: the model's probability and the advised side are what
    they were when the line was priced.
    """
    import model as m
    book = request.args.get("book")
    book = book if book in TENNIS_BOOKS else None
    if not one("SELECT to_regclass('aces.line') AS t")["t"]:
        rows = []
    else:
        rows = query("""
            SELECT l.*, (l.p_over::float) AS p, (l.line::float) AS ln,
                   (l.over_odds::float) AS oo, (l.under_odds::float) AS uo,
                   (l.model_mean::float) AS mean
              FROM aces.line l
             ORDER BY l.date DESC, l.player_1, l.market, l.line""")
    settled, pending, void = [], [], []
    for r in rows:
        r = dict(r)
        r["book"] = r.get("source") if r.get("source") in TENNIS_BOOKS else "manual"
        if book and r["book"] != book:
            continue
        stat, _sep, who = r["market"].partition(":")
        r["stat"] = stat                       # aces | df
        r["about"] = {"1": r["player_1"], "2": r["player_2"]}.get(who)
        # An unadvised line still shows the price and the model's edge on it,
        # the over side unless only an under was quoted.
        side = r["bet"] or ("over" if r["oo"] else "under" if r["uo"] else None)
        r["odds"] = r["oo"] if side == "over" else r["uo"] if side == "under" else None
        r["p_bet"] = (r["p"] if side == "over" else 1 - r["p"]) if side else None
        r["edge"] = r["p_bet"] * r["odds"] - 1 if r["odds"] else None
        # Betano quotes "N or more"; show it that way rather than as N - 0.5.
        r["line_label"] = (f"{r['ln'] + 0.5:.0f}+" if r.get("source") == "betano"
                           else f"{r['ln']:.1f}")
        if r["void"]:
            void.append(r)
        elif r["actual"] is None:
            pending.append(r)
        else:
            if r["bet"] == "over":
                r["hit"] = r["actual"] > r["ln"]
            elif r["bet"] == "under":
                r["hit"] = r["actual"] < r["ln"]
            # Profit on a 1-unit stake, for the results list at the top.
            r["pl"] = ((r["odds"] - 1 if r["hit"] else -1.0)
                       if r["bet"] and r["odds"] else None)
            settled.append(r)

    bets = [r for r in settled if r["bet"] and r["odds"]]
    returned = sum(r["odds"] for r in bets if r["hit"])
    totals = {"bets": len(bets), "won": sum(1 for r in bets if r["hit"]),
              "pnl": returned - len(bets),
              "roi": (returned - len(bets)) / len(bets) if bets else None,
              "no_bet": sum(1 for r in settled if not r["bet"])}
    call = m.verdict([(bool(r["hit"]), r["odds"]) for r in bets])
    if not session.get("admin"):
        # Visitors see advised bets only, as on the possession record.
        settled = [r for r in settled if r["bet"]]
        pending = [r for r in pending if r["bet"]]
        void = []
    # Upcoming: advised bets first, each group by kick-off.
    far = datetime.max.replace(tzinfo=timezone.utc)
    pending.sort(key=lambda r: (r["bet"] is None, r["kickoff"] or far, r["player_1"], r["market"]))
    # Newest first for the results list; the full table stays sortable.
    latest = sorted([r for r in settled if r["bet"]],
                    key=lambda r: (r["kickoff"] or datetime.min.replace(tzinfo=timezone.utc), r["date"]),
                    reverse=True)[:10]
    return render_template("tennis.html", settled=settled, pending=pending, void=void,
                           totals=totals, verdict=call, user=session.get("admin"),
                           book=book, books=TENNIS_BOOKS, latest=latest)


@app.route("/tennis/compare")
@members_only
def tennis_compare():
    """Every bookmaker's ace and DF prices beside the model's fair price.
    Admin only: model prices on every line are tips in all but name."""
    return render_template("tennis_compare.html", compare=_tennis_compare(), books=TENNIS_BOOKS)


@app.route("/tennis/status")
@members_only
def tennis_status():
    """Is the aces pipeline alive? When each bookmaker was last collected and
    how often, what is on offer and how much of it could be priced, and how
    fresh the tour data the ratings come from is."""
    if not one("SELECT to_regclass('aces.odds') AS t")["t"]:
        return render_template("tennis_status.html", books=TENNIS_BOOKS, collections=[],
                               tours=[], unmatched=[], lines={})
    collections = query("""
        SELECT e.source,
               max(o.fetched_at) AS last_fetch,
               count(DISTINCT o.fetched_at) FILTER (WHERE o.fetched_at > now() - interval '24 hours') AS runs_24h,
               count(DISTINCT e.event_id) FILTER (WHERE e.kickoff > now()) AS upcoming,
               count(DISTINCT e.event_id) FILTER (WHERE e.kickoff > now()
                     AND (e.player_1_id IS NULL OR e.player_2_id IS NULL)) AS unmatched,
               count(DISTINCT e.event_id) FILTER (WHERE e.kickoff > now() AND e.tour = 'WTA') AS wta,
               count(DISTINCT e.event_id) FILTER (WHERE e.kickoff > now() AND e.tour = 'ATP') AS atp
          FROM aces.event e LEFT JOIN aces.odds o USING (source, event_id)
         GROUP BY e.source ORDER BY e.source""")
    tours = query("""
        SELECT m.tour, count(*) AS matches, max(m.played_at) AS latest,
               count(*) FILTER (WHERE m.played_at > now() - interval '7 days') AS last_7d,
               count(*) FILTER (WHERE m.completed) AS completed
          FROM aces.match m GROUP BY m.tour ORDER BY m.tour""")
    unmatched = query("""
        SELECT e.source, e.tour, e.kickoff, e.league, e.name_1, e.name_2,
               e.player_1_id IS NULL AS miss_1, e.player_2_id IS NULL AS miss_2
          FROM aces.event e
         WHERE e.kickoff > now() AND (e.player_1_id IS NULL OR e.player_2_id IS NULL)
         ORDER BY e.kickoff""")
    lines = one("""
        SELECT count(*) FILTER (WHERE bet IS NOT NULL AND actual IS NULL AND void IS NOT TRUE
                                  AND kickoff > now()) AS open_bets,
               count(*) FILTER (WHERE bet IS NOT NULL AND actual IS NULL AND void IS NOT TRUE
                                  AND kickoff <= now()) AS awaiting_result,
               count(*) FILTER (WHERE bet IS NOT NULL AND actual IS NOT NULL) AS settled_bets,
               max(priced_at) AS last_priced
          FROM aces.line""")
    return render_template("tennis_status.html", books=TENNIS_BOOKS, collections=collections,
                           tours=tours, unmatched=unmatched, lines=lines)


def _tennis_compare():
    """Every upcoming match's ace and DF prices, bookmaker beside bookmaker.

    One row per market and threshold ("at least N", the over side of N - 0.5):
    the model's fair prices, then each bookmaker's latest over (and under,
    where it quotes one). A match is the same at every bookmaker through
    aces.event.match_key. Bookmakers list the players in different orders, so
    each one's player 1 and 2 are mapped onto the match key's order first -
    otherwise Betano's "aces:1" and Chance's "aces:1" could be two players.
    """
    if not one("SELECT to_regclass('aces.odds') AS t")["t"]:
        return []
    rows = query("""
        SELECT e.source, e.event_id, e.kickoff, e.league, e.tour, e.match_key,
               e.name_1, e.name_2, e.player_1_id, e.player_2_id,
               o.market, o.at_least, o.side, o.price::float AS price, o.p_model::float AS p_model
          FROM aces.event e
          JOIN aces.odds o USING (source, event_id)
         WHERE e.kickoff > now() AND e.match_key IS NOT NULL
           AND o.fetched_at = (SELECT max(fetched_at) FROM aces.odds x
                                WHERE (x.source, x.event_id) = (e.source, e.event_id))
         ORDER BY e.kickoff, e.match_key""")
    import unicodedata

    def words(name):
        s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        return " ".join(sorted(re.sub(r"[^a-z ]", " ", s).split()))

    matches = {}
    for r in rows:
        _date, key_a, key_b = r["match_key"].split("|")
        m = matches.setdefault(r["match_key"], {
            "kickoff": r["kickoff"], "tour": r["tour"], "league": r["league"],
            "names": {}, "rows": {}, "books": set()})
        # Which of this bookmaker's players is the key's first?
        first_is_1 = (r["player_1_id"] == key_a) if r["player_1_id"] else (words(r["name_1"]) == key_a)
        names = (r["name_1"], r["name_2"]) if first_is_1 else (r["name_2"], r["name_1"])
        if r["source"] == "betano" or not m["names"]:
            m["names"] = {"A": names[0], "B": names[1]}
        stat, _, who = r["market"].partition(":")
        if who:
            who = "A" if (who == "1") == first_is_1 else "B"
        cell = m["rows"].setdefault((stat, who, r["at_least"]), {"p": None, "books": {}})
        if r["p_model"] is not None:
            cell["p"] = r["p_model"]
        cell["books"].setdefault(r["source"], {})[r["side"]] = r["price"]
        m["books"].add(r["source"])

    out = []
    for key, m in matches.items():
        lines, best = [], None
        for (stat, who, n), cell in sorted(m["rows"].items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
            p = cell["p"]
            line = {"stat": stat, "about": m["names"].get(who) if who else None, "n": n,
                    "label": f"{n - 0.5:.1f}", "p": p,
                    "fair_over": 1 / p if p else None, "fair_under": 1 / (1 - p) if p and p < 1 else None,
                    "books": cell["books"], "best": {}}
            for side in ("over", "under"):
                quotes = [(b, q[side]) for b, q in cell["books"].items() if q.get(side)]
                if not quotes:
                    continue
                b, price = max(quotes, key=lambda bq: bq[1])
                ev = (p * price - 1 if side == "over" else (1 - p) * price - 1) if p is not None else None
                # Only aces are trusted: on double faults the model ties each
                # player's own average (aces backtest), so a DF "edge" is shown
                # but never highlighted or offered as the match's best.
                line["best"][side] = {"book": b, "price": price, "ev": ev, "trusted": stat == "aces"}
                if ev is not None and stat == "aces" and (best is None or ev > best["ev"]):
                    best = {"ev": ev, "book": b, "side": side, "stat": stat,
                            "about": line["about"], "label": line["label"], "price": price}
            lines.append(line)
        out.append({"key": key, "kickoff": m["kickoff"], "tour": m["tour"], "league": m["league"],
                    "match": f"{m['names'].get('A')} v {m['names'].get('B')}",
                    "books": sorted(m["books"]), "lines": lines, "best": best,
                    "priced": any(l["p"] is not None for l in lines)})
    return out


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_advice"))


@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    """Upload a spreadsheet of lines, review what it means, then commit it.

    The preview is not decoration. A mis-read column reverses which side a bet
    is recorded on, and that corrupts the record the model is judged by - so
    nothing is written until the parsed rows have been shown as plain English.
    """
    import import_odds as io_mod
    import odds_sheet

    preview = problems = None
    written = None
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "commit":
                # Re-parse the stashed upload rather than trusting a round trip
                # through the form: fewer places for the values to change.
                token = session.get("upload_token")
                name = session.get("upload_name", "")
                path = _staged_path(token) if token else None
                if not path or not path.exists():
                    raise ValueError(_("Nothing staged - upload the file again."))
                parsed = odds_sheet.parse_bytes(path.read_bytes(), name)
                ready, problems = io_mod.resolve_rows(db_handle(), parsed)
                for r in ready:
                    r.pop("_label", None)
                    r.pop("_flipped", None)
                written = db_handle().upsert_lines(ready)
                path.unlink(missing_ok=True)
                session.pop("upload_token", None)
                session.pop("upload_name", None)
            else:
                pasted = (request.form.get("pasted") or "").strip()
                upload = request.files.get("sheet")
                if pasted:
                    # Pasting from a spreadsheet or the bookmaker's table gives
                    # tab-separated text, which is exactly what the file
                    # importer already reads - so it goes through the same
                    # parser rather than a second one that could disagree.
                    raw = pasted.encode("utf-8")
                    name = "pasted.tsv"
                elif upload and upload.filename:
                    raw = upload.read()
                    name = upload.filename
                else:
                    raise ValueError(_("Paste some rows or choose a file."))
                # A paste with no header row is the common case: people copy
                # the data rows and leave the titles behind, and the compact
                # form has no header at all. parse_bytes RAISES on a missing
                # header rather than returning nothing, so the fallback has to
                # catch - testing `if not parsed` never ran, and every compact
                # paste died with a message about spreadsheet headers.
                header_problem = None
                try:
                    parsed = odds_sheet.parse_bytes(raw, name)
                except ValueError as exc:
                    parsed, header_problem = [], exc
                if not parsed:
                    parsed = import_odds_parse_text(raw.decode("utf-8", "replace"))
                if not parsed:
                    raise ValueError(
                        _("No rows understood. Include a header row naming the "
                          "columns, or paste lines in the compact form: "
                          "date  club  club  team  line  O<over>  U<under>")
                        + (f"  ({header_problem})" if header_problem else ""))
                preview, problems = io_mod.resolve_rows(db_handle(), parsed)
                # The file is staged on disk, not in the session. Flask keeps
                # session data in a cookie, and browsers silently drop cookies
                # over about 4KB - a real spreadsheet is bigger than that, so
                # stashing it there fails only in a real browser, never in a
                # test.
                token = secrets.token_urlsafe(16)
                _staged_path(token).write_bytes(raw)
                session["upload_token"] = token
                # `name`, not upload.filename: on a paste there may be no file
                # part at all, and None has no .filename.
                session["upload_name"] = name
        except Exception as exc:          # surfaced to the page, not swallowed
            error = str(exc)

    recent = query("""
        SELECT l.line, l.over_odds, l.under_odds, l.captured_at, l.bookmaker,
               t.name AS team, ht.abbr AS home_abbr, at_.abbr AS away_abbr,
               m.kickoff
        FROM pl_possession_line l
        JOIN pl_teams t   ON t.team_id = l.team_id
        JOIN pl_matches m ON m.match_id = l.match_id
        JOIN pl_teams ht  ON ht.team_id = m.home_team_id
        JOIN pl_teams at_ ON at_.team_id = m.away_team_id
        ORDER BY l.captured_at DESC NULLS LAST, m.kickoff DESC
        LIMIT 25
    """)
    return render_template("admin.html", preview=preview, problems=problems,
                           written=written, error=error, recent=recent,
                           user=session.get("admin"))


def import_odds_parse_text(text):
    """Parse pasted lines with the text importer, via a temporary file.

    import_odds.parse reads a path rather than a string; rather than duplicate
    its two format branches here - where the copy would drift - the paste is
    written out and handed to the same function the command line uses.
    """
    import import_odds as io_mod
    tmp = Path(tempfile.gettempdir()) / f"pl-odds-paste-{secrets.token_hex(8)}.txt"
    try:
        tmp.write_text(text, encoding="utf-8")
        return io_mod.parse(str(tmp))
    finally:
        tmp.unlink(missing_ok=True)


def _staged_path(token):
    """Where an uploaded sheet waits between preview and commit.

    The token is generated here, never taken from the request, so a crafted
    value cannot point this at another file.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(token))[:40]
    staging = Path(tempfile.gettempdir()) / "pl-odds-staging"
    staging.mkdir(exist_ok=True)
    return staging / f"{safe}.upload"


def db_handle():
    """A Database wrapper around this request's connection, for the upserts."""
    import db as db_mod
    handle = db_mod.Database.__new__(db_mod.Database)
    handle.conn = db()
    handle.dsn = os.getenv("DATABASE_URL")
    return handle


# On the server (DEPLOYED is set only in the web service's unit, not for the
# cron jobs that also import this module) load every league's data as soon as
# a worker starts.
if DEPLOYED:
    warm_caches()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
