"""PostgreSQL sink (Neon or any Postgres).

  pl_teams            one row per club
  pl_matches          one row per match, played AND scheduled
  pl_team_appearance  every fixture in any competition - the rest-day calendar
  pl_team_match       one row per team per match, that team's own stat line

Scheduled matches are stored too: predicting next weekend needs a row to
predict against, and v_fixture_features supplies its features from the same
windows used for training rows.

Connection comes from DATABASE_URL, which is what Neon hands you:
  postgresql://user:password@host/dbname?sslmode=require
"""

import logging
import os
import re
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from features import (AGAINST_COLUMNS, ALL_COLUMNS, STAT_COLUMNS, sql_type,
                      stat_columns_ddl)

log = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent

TEAMS_DDL = """
CREATE TABLE IF NOT EXISTS pl_teams (
  team_id    TEXT PRIMARY KEY,
  name       TEXT,
  short_name TEXT,
  abbr       TEXT,
  stadium    TEXT,
  city       TEXT,
  capacity   INTEGER
)
"""

MATCHES_DDL = """
CREATE TABLE IF NOT EXISTS pl_matches (
  match_id     TEXT PRIMARY KEY,
  season       TEXT,
  match_week   SMALLINT,
  kickoff      TIMESTAMP,
  ground       TEXT,
  period       TEXT,
  home_team_id TEXT,
  away_team_id TEXT,
  home_score   SMALLINT,
  away_score   SMALLINT,
  first_seen   TIMESTAMP NOT NULL DEFAULT NOW(),
  last_seen    TIMESTAMP NOT NULL DEFAULT NOW()
)
"""

# Every competitive fixture a tracked team plays, in ANY competition. Only
# league matches get a full stat line in pl_team_match; this table exists so
# rest days and congestion reflect the real calendar, including midweek
# European and cup games.
APPEARANCE_DDL = """
CREATE TABLE IF NOT EXISTS pl_team_appearance (
  match_id       TEXT NOT NULL,
  team_id        TEXT NOT NULL,
  competition_id TEXT,
  competition    TEXT,
  season         TEXT,
  kickoff        TIMESTAMP,
  is_home        SMALLINT,
  opponent_id    TEXT,
  opponent_name  TEXT,
  period         TEXT,
  goals_for      SMALLINT,
  goals_against  SMALLINT,
  last_seen      TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, team_id)
)
"""

TEAM_MATCH_DDL = """
CREATE TABLE IF NOT EXISTS pl_team_match (
  match_id    TEXT NOT NULL,
  team_id     TEXT NOT NULL,
  opponent_id TEXT,
  is_home     SMALLINT,
  season      TEXT,
  match_week  SMALLINT,
  kickoff     TIMESTAMP,
  result      TEXT,
  points      SMALLINT,
{stats}
  first_seen  TIMESTAMP NOT NULL DEFAULT NOW(),
  last_seen   TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, team_id)
)
"""

# Goals with the minute they were scored. This is what makes game state
# knowable: possession and xG are only published as whole-match totals, but
# with goal minutes we can at least say how long each side spent ahead, level
# or behind, and treat a 42%-possession side that led for an hour differently
# from one that was chasing.
#
# goal_type is Goal / Own / Penalty. Own goals are filed under the team that
# BENEFITS (verified against 30 matches: event counts matched every stored
# scoreline), so team_id is always the side the goal counts for.
GOALS_DDL = """
CREATE TABLE IF NOT EXISTS pl_match_goal (
  match_id         TEXT NOT NULL,
  team_id          TEXT NOT NULL,
  minute           SMALLINT NOT NULL,
  period           TEXT,
  goal_type        TEXT,
  player_id        TEXT,
  assist_player_id TEXT,
  last_seen        TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, team_id, minute, player_id)
)
"""

CARDS_DDL = """
CREATE TABLE IF NOT EXISTS pl_match_card (
  match_id  TEXT NOT NULL,
  team_id   TEXT NOT NULL,
  minute    SMALLINT NOT NULL,
  period    TEXT,
  card_type TEXT,
  player_id TEXT NOT NULL,
  last_seen TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, player_id, minute, card_type)
)
"""

SUBS_DDL = """
CREATE TABLE IF NOT EXISTS pl_match_sub (
  match_id       TEXT NOT NULL,
  team_id        TEXT NOT NULL,
  minute         SMALLINT NOT NULL,
  period         TEXT,
  player_on_id   TEXT NOT NULL,
  player_off_id  TEXT,
  last_seen      TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, player_on_id, minute)
)
"""

# The starting XI and bench. line_index is the row the player occupies in the
# formation as the API reports it: 0 is the keeper, then each outfield band in
# order, so a 4-2-3-1 gives holding midfielders line_index 2 and the attacking
# three line_index 3. That distinction is the whole point - "Midfielder" alone
# lumps a destroyer in with a number 10.
LINEUP_DDL = """
CREATE TABLE IF NOT EXISTS pl_lineup (
  match_id   TEXT NOT NULL,
  team_id    TEXT NOT NULL,
  player_id  TEXT NOT NULL,
  position   TEXT,
  shirt_num  SMALLINT,
  is_captain SMALLINT,
  is_starter SMALLINT,
  line_index SMALLINT,
  formation  TEXT,
  last_seen  TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, player_id)
)
"""

PLAYERS_DDL = """
CREATE TABLE IF NOT EXISTS pl_player (
  player_id  TEXT PRIMARY KEY,
  first_name TEXT,
  last_name  TEXT,
  last_seen  TIMESTAMP NOT NULL DEFAULT NOW()
)
"""

# Bookmaker possession lines. This is the only table here not filled by the
# scraper - the odds are entered by hand from the bookmaker's site.
#
# Why it matters more than its size suggests: without recorded lines, a model's
# "edge" is a number it computes about itself. With them you can ask the only
# question that decides whether to bet - would backing my edges actually have
# made money - and the answer stops being an opinion.
#
# BOTH prices are wanted, not just the one being considered. Implied
# probabilities on the two sides sum to more than 1, and that excess is the
# bookmaker's margin. Without the other side you cannot strip it out, and
# comparing a model against a margin-inflated probability flatters it.
#
# team_id says whose possession the line refers to: "Arsenal over/under 54.5"
# and "Chelsea over/under 45.5" are the same market priced from either end.
LINES_DDL = """
CREATE TABLE IF NOT EXISTS pl_possession_line (
  match_id    TEXT NOT NULL,
  team_id     TEXT NOT NULL,
  line        NUMERIC(5,2) NOT NULL,
  over_odds   NUMERIC(6,3),
  under_odds  NUMERIC(6,3),
  bookmaker   TEXT NOT NULL DEFAULT 'chance.cz',
  is_closing  SMALLINT,
  captured_at TIMESTAMP,
  note        TEXT,
  last_seen   TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, team_id, line, bookmaker)
)
"""

# What each odds run did. Written by odds_pipeline.py, read by the Scraper
# page - the only record of whether a scheduled run fired, what it cost, and
# whether anything reached the database. webscraper.io keeps its own job list,
# but it cannot know whether a scraped market resolved to a fixture and was
# stored, which is the half that actually matters.
SCRAPE_RUN_DDL = """
CREATE TABLE IF NOT EXISTS pl_scrape_run (
  run_id       BIGSERIAL PRIMARY KEY,
  started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at  TIMESTAMPTZ,
  source       TEXT,              -- 'github-actions' or 'local'
  hours        INTEGER,
  skip_priced  BOOLEAN,
  stage1_job   TEXT,
  stage2_job   TEXT,
  fixtures     INTEGER,           -- in the kickoff window
  pages        INTEGER,           -- match pages actually scraped
  unmatched    INTEGER,
  ambiguous    INTEGER,
  superseded   INTEGER,
  rows_back    INTEGER,           -- rows stage 2 returned
  resolved     INTEGER,           -- lines that found their fixture
  problems     INTEGER,
  written      INTEGER,           -- lines that reached the database
  credits      INTEGER,           -- remaining, read after the run
  status       TEXT NOT NULL DEFAULT 'running',
  detail       TEXT               -- problems, or the traceback on a crash
)
"""

# How many times a fixture's page has been opened without a possession market
# appearing on it. Chance prices some matches and never prices others, and
# without this the ones it never prices are re-scraped every run forever - one
# credit each, several times a day, to learn the same nothing.
#
# Only empty attempts are counted. A fixture that yields a line has one
# recorded against it too, but it then carries odds and is skipped as priced,
# so the count stops mattering.
ODDS_ATTEMPT_DDL = """
CREATE TABLE IF NOT EXISTS pl_odds_attempt (
  match_id     TEXT PRIMARY KEY,
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_attempt TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_found   BOOLEAN NOT NULL DEFAULT FALSE
)
"""

# Each league's measured prediction spread - see calibration.py. One row per
# league, replaced on every measurement; the history of past values is not
# kept because nothing reads it, and measured_at says how fresh the one is.
CALIBRATION_DDL = """
CREATE TABLE IF NOT EXISTS pl_model_calibration (
  competition  TEXT PRIMARY KEY,
  sigma        NUMERIC(6,3) NOT NULL,
  mae          NUMERIC(6,3),
  naive_mae    NUMERIC(6,3),
  n            INTEGER NOT NULL,
  within_1     NUMERIC(5,3),
  within_164   NUMERIC(5,3),
  within_196   NUMERIC(5,3),
  measured_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# Who managed each side in each match, read from the lineups the scrapers
# already fetch. Stored per match rather than as appointment dates because no
# source publishes appointment dates, and per match is what the model needs:
# a change shows up as the id changing between one match and the next.
#
# Premier League and LaLiga only. bundesliga.com carries no coach in the page
# state we can read.
MANAGER_DDL = """
CREATE TABLE IF NOT EXISTS pl_match_manager (
  match_id     TEXT NOT NULL,
  team_id      TEXT NOT NULL,
  manager_id   TEXT NOT NULL,
  manager_name TEXT,
  last_seen    TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, team_id)
)
"""
MANAGER_COLS = ["match_id", "team_id", "manager_id", "manager_name"]

# The advice the site actually gave, frozen at kickoff.
#
# The Learning page recomputes every past bet with today's model, so a change
# to the model or to sigma rewrites what it says was advised - on 14 Sep one
# fix changed the advised side of 5 of 30 settled bets. That page is for
# learning; it cannot be a record. This table is the record.
#
# One row per match. Rewritten on every run while kickoff is still in the
# future, so it follows the site as lines and the model move, and never
# written again after kickoff: the WHERE on the conflict update enforces that
# in the database rather than trusting the caller. What survives is the last
# advice the site showed before the match began - the same run renders both.
ADVICE_DDL = """
CREATE TABLE IF NOT EXISTS pl_advice (
  match_id          TEXT NOT NULL,
  bookmaker         TEXT NOT NULL,
  competition       TEXT,
  kickoff           TIMESTAMP NOT NULL,
  team_id           TEXT NOT NULL,
  line              NUMERIC(5,2) NOT NULL,
  over_odds         NUMERIC(6,3),
  under_odds        NUMERIC(6,3),
  pred              NUMERIC(6,2),
  sigma             NUMERIC(6,3),
  p_over            NUMERIC(6,4),
  side              TEXT,
  odds              NUMERIC(6,3),
  edge              NUMERIC(7,4),
  rating            SMALLINT,
  backed            BOOLEAN NOT NULL,
  fallback          BOOLEAN NOT NULL,
  why               TEXT,
  code_version      TEXT,
  first_advised_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  advised_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (match_id, bookmaker)
)
"""
ADVICE_COLS = ["match_id", "bookmaker", "competition", "kickoff", "team_id",
               "line", "over_odds", "under_odds", "pred", "sigma", "p_over",
               "side", "odds", "edge", "rating", "backed", "fallback", "why",
               "code_version"]

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_tm_team_kickoff ON pl_team_match (team_id, kickoff)",
    "CREATE INDEX IF NOT EXISTS idx_tm_kickoff ON pl_team_match (kickoff)",
    "CREATE INDEX IF NOT EXISTS idx_app_team_kickoff ON pl_team_appearance (team_id, kickoff)",
    "CREATE INDEX IF NOT EXISTS idx_matches_kickoff ON pl_matches (kickoff)",
    "CREATE INDEX IF NOT EXISTS idx_matches_period ON pl_matches (period)",
    "CREATE INDEX IF NOT EXISTS idx_goal_match ON pl_match_goal (match_id, minute)",
    "CREATE INDEX IF NOT EXISTS idx_sub_match ON pl_match_sub (match_id)",
    "CREATE INDEX IF NOT EXISTS idx_lineup_match_team ON pl_lineup (match_id, team_id)",
    "CREATE INDEX IF NOT EXISTS idx_lineup_player ON pl_lineup (player_id)",
    "CREATE INDEX IF NOT EXISTS idx_line_match ON pl_possession_line (match_id)",
    "CREATE INDEX IF NOT EXISTS idx_run_started ON pl_scrape_run (started_at DESC)",
)

GOAL_COLS = ("match_id", "team_id", "minute", "period", "goal_type",
             "player_id", "assist_player_id")
CARD_COLS = ("match_id", "team_id", "minute", "period", "card_type", "player_id")
SUB_COLS = ("match_id", "team_id", "minute", "period", "player_on_id",
            "player_off_id")
LINEUP_COLS = ("match_id", "team_id", "player_id", "position", "shirt_num",
               "is_captain", "is_starter", "line_index", "formation")
PLAYER_COLS = ("player_id", "first_name", "last_name")
LINE_COLS = ("match_id", "team_id", "line", "over_odds", "under_odds",
             "bookmaker", "is_closing", "captured_at", "note")

TEAM_COLS = ("competition", "team_id", "name", "short_name", "abbr", "stadium", "city", "capacity")
MATCH_COLS = ("competition", "match_id", "season", "match_week", "kickoff", "ground", "period",
              "home_team_id", "away_team_id", "home_score", "away_score")
APPEARANCE_COLS = ("match_id", "team_id", "competition_id", "competition", "season",
                   "kickoff", "is_home", "opponent_id", "opponent_name", "period",
                   "goals_for", "goals_against")


def team_match_ddl():
    return TEAM_MATCH_DDL.format(stats=stat_columns_ddl())


def _upsert_sql(table, columns, keys, touch_last_seen=True, keep_first=()):
    """Postgres upsert. EXCLUDED is the row that failed to insert.

    keep_first names columns that record when something first happened. They
    are written once and never replaced, whatever later writes carry.
    """
    cols = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    updates = [(f"{c} = COALESCE({table}.{c}, EXCLUDED.{c})" if c in keep_first
                else f"{c} = EXCLUDED.{c}")
               for c in columns if c not in keys]
    if touch_last_seen:
        updates.append("last_seen = NOW()")
    return (f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {', '.join(updates)}")


class Database:
    def __init__(self, dsn=None):
        dsn = dsn or os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL is not set. Copy .env.example to .env and paste "
                "the connection string from your Neon dashboard."
            )
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
        # Never log the password.
        log.info("Connected to Postgres (%s)", re.sub(r"://[^@]*@", "://***@", dsn))

    def ensure_connection(self):
        """Reconnect if the connection died while we were busy elsewhere.

        main.py connects up front so a bad connection string fails in a second
        rather than after minutes of scraping. The cost of that is a connection
        sitting idle for the whole scrape, and Neon's pooler closes idle
        connections - so by the time there is something to write, the handle can
        be dead. Cheaper to check than to lose a completed scrape.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
            return False
        except Exception:
            log.info("Connection dropped during the scrape - reconnecting.")
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = psycopg.connect(self.dsn, row_factory=dict_row,
                                        autocommit=False)
            return True

    def ensure_schema(self, with_views=True):
        with self.conn.cursor() as cur:
            cur.execute(TEAMS_DDL)
            cur.execute(MATCHES_DDL)
            cur.execute(APPEARANCE_DDL)
            cur.execute(team_match_ddl())
            cur.execute(GOALS_DDL)
            cur.execute(CARDS_DDL)
            cur.execute(SUBS_DDL)
            cur.execute(LINEUP_DDL)
            cur.execute(PLAYERS_DDL)
            cur.execute(LINES_DDL)
            cur.execute(SCRAPE_RUN_DDL)
            cur.execute(ODDS_ATTEMPT_DDL)
            cur.execute(CALIBRATION_DDL)
            cur.execute(MANAGER_DDL)
            cur.execute(ADVICE_DDL)
            for stmt in INDEXES:
                cur.execute(stmt)
        self.conn.commit()
        self.migrate_competitions()
        self.migrate_stat_columns()
        self.migrate_notifications()
        if with_views:
            self.ensure_views()

    def migrate_competitions(self):
        """Add the competition dimension to the per-league tables.

        The schema began as Premier League only. Existing rows are backfilled
        to 'PL' rather than being rewritten, so nothing already collected moves
        or is reinterpreted.

        Team and match ids are NOT namespaced. The Premier League's are small
        integers and the German and Spanish feeds use DFL-/LaLiga-prefixed
        strings, so they cannot collide; a prefix would only make every
        existing id churn for no gain.
        """
        added = []
        with self.conn.cursor() as cur:
            # pl_team_appearance is deliberately absent: it already has a
            # `competition` column naming the competition of that fixture
            # (league, cup, Europe), which is what a rest-day calendar needs.
            # Reusing the name for "which league does this club play in" would
            # overload one column with two meanings.
            for table in ("pl_teams", "pl_matches", "pl_team_match"):
                cur.execute("""SELECT 1 FROM information_schema.columns
                               WHERE table_name = %s AND column_name = 'competition'""",
                            (table,))
                if cur.fetchone():
                    continue
                cur.execute(f"ALTER TABLE {table} ADD COLUMN competition TEXT")
                cur.execute(f"UPDATE {table} SET competition = 'PL' "
                            f"WHERE competition IS NULL")
                cur.execute(f"ALTER TABLE {table} "
                            f"ALTER COLUMN competition SET DEFAULT 'PL'")
                cur.execute(f"ALTER TABLE {table} "
                            f"ALTER COLUMN competition SET NOT NULL")
                cur.execute(f"CREATE INDEX IF NOT EXISTS "
                            f"idx_{table}_competition ON {table} (competition)")
                added.append(table)
        self.conn.commit()
        if added:
            log.info("Added competition column to: %s", ", ".join(added))
        return added

    def migrate_stat_columns(self):
        """Add stat columns that features.py has gained since the table was made.

        CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so without
        this a new entry in STAT_MAP would be silently dropped on write instead
        of stored - the failure mode being a column of NULLs nobody notices.
        """
        with self.conn.cursor() as cur:
            cur.execute("""SELECT column_name FROM information_schema.columns
                           WHERE table_name = 'pl_team_match'""")
            have = {r["column_name"] for r in cur.fetchall()}
            missing = [c for c in STAT_COLUMNS + AGAINST_COLUMNS if c not in have]
            for col in missing:
                cur.execute(f"ALTER TABLE pl_team_match "
                            f"ADD COLUMN IF NOT EXISTS {col} {sql_type(col)}")
        self.conn.commit()
        if missing:
            log.info("Added %d new stat column(s): %s",
                     len(missing), ", ".join(missing))
        return missing

    def migrate_notifications(self):
        """Give possession lines a notified_at, for the Telegram alerts.

        When the column is first added, every line already stored is marked as
        notified in the same transaction. Otherwise the first run after
        installing notifications would announce every line ever recorded,
        including matches played weeks ago. Only lines captured from here on
        are news.
        """
        with self.conn.cursor() as cur:
            cur.execute("""SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'pl_possession_line'
                             AND column_name = 'notified_at'""")
            if cur.fetchone():
                return False
            cur.execute("ALTER TABLE pl_possession_line "
                        "ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ")
            cur.execute("UPDATE pl_possession_line SET notified_at = NOW() "
                        "WHERE notified_at IS NULL")
            marked = cur.rowcount
        self.conn.commit()
        log.info("Added notified_at; marked %d existing line(s) as already "
                 "notified", marked)
        return True

    def ensure_views(self):
        """(Re)create the modelling views from views.sql."""
        sql = (BASE_DIR / "views.sql").read_text(encoding="utf-8")
        # Strip whole-line comments BEFORE splitting: prose can contain a
        # semicolon, and splitting first turns half a sentence into a statement.
        sql = re.sub(r"^\s*--.*$", "", sql, flags=re.M)
        with self.conn.cursor() as cur:
            for stmt in (s.strip() for s in sql.split(";")):
                if stmt:
                    cur.execute(stmt)
        self.conn.commit()
        log.info("Modelling views created/refreshed.")

    # -- writes ------------------------------------------------------------

    def _upsert(self, table, cols, rows, keys, touch=True, batch=500,
                keep_first=()):
        if not rows:
            return 0
        sql = _upsert_sql(table, cols, keys, touch, keep_first)
        tuples = [tuple(r.get(c) for c in cols) for r in rows]
        with self.conn.cursor() as cur:
            for i in range(0, len(tuples), batch):
                cur.executemany(sql, tuples[i:i + batch])
        self.conn.commit()
        return len(tuples)

    def upsert_teams(self, teams):
        # pl_teams has no last_seen column.
        return self._upsert("pl_teams", TEAM_COLS, teams, ("team_id",), touch=False)

    def upsert_matches(self, matches):
        return self._upsert("pl_matches", MATCH_COLS, matches, ("match_id",))

    def upsert_appearances(self, rows):
        return self._upsert("pl_team_appearance", APPEARANCE_COLS, rows,
                            ("match_id", "team_id"))

    def upsert_team_matches(self, rows):
        n = self._upsert("pl_team_match", ALL_COLUMNS, rows, ("match_id", "team_id"))
        return {"written": n}

    def upsert_goals(self, rows):
        return self._upsert("pl_match_goal", GOAL_COLS, rows,
                            ("match_id", "team_id", "minute", "player_id"))

    def upsert_cards(self, rows):
        return self._upsert("pl_match_card", CARD_COLS, rows,
                            ("match_id", "player_id", "minute", "card_type"))

    def upsert_subs(self, rows):
        return self._upsert("pl_match_sub", SUB_COLS, rows,
                            ("match_id", "player_on_id", "minute"))

    def upsert_lineups(self, rows):
        return self._upsert("pl_lineup", LINEUP_COLS, rows,
                            ("match_id", "player_id"))

    def freeze_advice(self, rows):
        """Record current advice for matches that have not kicked off.

        Returns (inserted_or_updated, refused). A row for a match whose kickoff
        has passed is refused twice over: the insert is skipped here, and the
        conflict update carries WHERE pl_advice.kickoff > now(), so even a
        caller that got the time wrong cannot rewrite frozen advice.
        """
        if not rows:
            return 0, 0
        cols = ", ".join(ADVICE_COLS)
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in ADVICE_COLS
                         if c not in ("match_id", "bookmaker"))
        sql = (f"INSERT INTO pl_advice ({cols}) "
               f"SELECT {', '.join(['%s'] * len(ADVICE_COLS))} "
               f"WHERE %s::timestamp > (now() AT TIME ZONE 'UTC') "
               f"ON CONFLICT (match_id, bookmaker) DO UPDATE SET {sets}, "
               f"advised_at = NOW() "
               f"WHERE pl_advice.kickoff > (now() AT TIME ZONE 'UTC')")
        written = refused = 0
        with self.conn.cursor() as cur:
            for r in rows:
                cur.execute(sql, [r.get(c) for c in ADVICE_COLS] + [r["kickoff"]])
                if cur.rowcount:
                    written += 1
                else:
                    refused += 1
        self.conn.commit()
        return written, refused

    def upsert_managers(self, rows):
        return self._upsert("pl_match_manager", MANAGER_COLS, rows,
                            ("match_id", "team_id"))

    def upsert_players(self, rows):
        return self._upsert("pl_player", PLAYER_COLS, rows, ("player_id",))

    def upsert_lines(self, rows, overwrite=True):
        """Write possession lines.

        captured_at is kept from the FIRST write. It used to be replaced on
        every upsert, and odds.txt is re-imported every hour, so hand-entered
        lines claimed to have been captured two days after their kickoff -
        which made "the first line recorded for a match" unknowable.

        overwrite=False inserts new lines and leaves existing ones alone. The
        hourly odds.txt import uses it: otherwise the file and the scraper,
        which write the same row, revert each other's prices every hour. An
        explicit import - the admin page, or the file run by hand - still
        overwrites, because that is how a mistyped price gets corrected.
        """
        keys = ("match_id", "team_id", "line", "bookmaker")
        if overwrite:
            return self._upsert("pl_possession_line", LINE_COLS, rows, keys,
                                keep_first=("captured_at",))
        if not rows:
            return 0
        cols = ", ".join(LINE_COLS)
        sql = (f"INSERT INTO pl_possession_line ({cols}) "
               f"VALUES ({', '.join(['%s'] * len(LINE_COLS))}) "
               f"ON CONFLICT ({', '.join(keys)}) DO NOTHING")
        inserted = 0
        with self.conn.cursor() as cur:
            for r in rows:
                cur.execute(sql, tuple(r.get(c) for c in LINE_COLS))
                inserted += cur.rowcount
        self.conn.commit()
        return inserted

    def upsert_calibration(self, row):
        cols = ["competition", "sigma", "mae", "naive_mae", "n",
                "within_1", "within_164", "within_196"]
        with self.conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO pl_model_calibration ({', '.join(cols)}, measured_at)
                VALUES ({', '.join('%(' + c + ')s' for c in cols)}, NOW())
                ON CONFLICT (competition) DO UPDATE SET
                {', '.join(f'{c} = EXCLUDED.{c}' for c in cols[1:])},
                measured_at = NOW()
            """, row)
        self.conn.commit()

    def record_attempts(self, scraped_ids, found_ids):
        """Note that these fixtures' pages were opened, and which paid off.

        An attempt that found a market resets the count rather than adding to
        it: the throttle is about pages that keep coming back empty, and a
        fixture that produced a line once is not that.
        """
        if not scraped_ids:
            return 0
        found = {str(f) for f in found_ids}
        rows = [(str(mid), str(mid) in found, str(mid) in found)
                for mid in scraped_ids]
        with self.conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO pl_odds_attempt (match_id, attempts, last_found)
                VALUES (%s, CASE WHEN %s THEN 0 ELSE 1 END, %s)
                ON CONFLICT (match_id) DO UPDATE
                SET attempts = CASE WHEN EXCLUDED.last_found
                                    THEN 0 ELSE pl_odds_attempt.attempts + 1 END,
                    last_attempt = NOW(),
                    last_found = EXCLUDED.last_found
            """, rows)
        self.conn.commit()
        return len(rows)

    def start_run(self, **fields):
        """Open a run row and return its id.

        Written before the scrape rather than after, so a run that crashes or
        is killed mid-way still leaves a trace. A row stuck at 'running' is
        itself the finding - it means the process died without reporting.
        """
        cols = [k for k in fields if fields[k] is not None]
        sql = (f"INSERT INTO pl_scrape_run ({', '.join(cols)}) "
               f"VALUES ({', '.join('%(' + c + ')s' for c in cols)}) "
               f"RETURNING run_id")
        with self.conn.cursor() as cur:
            cur.execute(sql, fields)
            run_id = cur.fetchone()["run_id"]
        self.conn.commit()
        return run_id

    def finish_run(self, run_id, **fields):
        """Record how a run ended. Never raises: a failure to log must not
        turn a successful scrape into a failed one."""
        if not run_id:
            return
        fields.setdefault("status", "ok")
        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        try:
            self.ensure_connection()
            with self.conn.cursor() as cur:
                cur.execute(f"UPDATE pl_scrape_run SET finished_at = NOW(), "
                            f"{sets} WHERE run_id = %(run_id)s",
                            {**fields, "run_id": run_id})
            self.conn.commit()
        except Exception:
            log.warning("could not record run %s", run_id, exc_info=True)

    def replace_match_events(self, match_id, goals, cards, subs):
        """Events are a full replacement per match, not an upsert.

        A goal can be reclassified (Goal -> Own) or its minute corrected on
        review. Upserting alone would leave the superseded row behind and
        double-count the goal, so the match's rows are cleared first.
        """
        with self.conn.cursor() as cur:
            for table in ("pl_match_goal", "pl_match_card", "pl_match_sub"):
                cur.execute(f"DELETE FROM {table} WHERE match_id = %s", (match_id,))
        self.conn.commit()
        return (self.upsert_goals(goals) + self.upsert_cards(cards)
                + self.upsert_subs(subs))

    # -- reads -------------------------------------------------------------

    def existing_match_ids(self, recheck_hours=48):
        """Matches we treat as settled. Recent ones are left out so their stats
        get re-fetched - Opta revises xG in the hours after a match."""
        sql = "SELECT DISTINCT match_id FROM pl_team_match"
        args = ()
        if recheck_hours > 0:
            sql += " WHERE kickoff < NOW() - (%s * INTERVAL '1 hour')"
            args = (int(recheck_hours),)
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            return {r["match_id"] for r in cur.fetchall()}

    def count(self, table="pl_team_match"):
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            return cur.fetchone()["n"]

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
