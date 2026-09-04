"""Load the modelling tables into pandas.

    from load import training_set, fixtures
    train = training_set(min_history=3)
    upcoming = fixtures()

Exists mostly to hide one sharp edge: SQLAlchemy maps a plain `postgresql://`
URL to psycopg2, which is not installed here (we use psycopg 3). Neon hands you
exactly that form of URL, so passing it straight to create_engine fails with a
confusing ModuleNotFoundError.
"""

import os
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# What the model predicts. Possession is zero-sum inside a match, so this one
# column defines the whole result: away possession is 100 minus it. Fitting a
# second model for the away side would only create two answers that can
# disagree with each other.
TARGET = "home_possession"


def _config():
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("premier_league", {}) or {}


def current_season():
    """The season the scraper treats as current - first in config's list."""
    seasons = _config().get("seasons") or []
    return str(seasons[0]) if seasons else None


def training_config():
    cfg = _config().get("training") or {}
    return {
        "season": cfg.get("season", "current"),
        "half_life_days": float(cfg.get("half_life_days", 30)),
        "min_history": int(cfg.get("min_history", 3)),
    }


def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set - see .env.example")
    # Force the psycopg 3 dialect.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):          # some hosts still emit this
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return create_engine(url)


def decay_weights(kickoffs, half_life_days=30, reference=None):
    """Exponential recency weights: 1.0 for the newest match, halving per
    half_life_days going back.

    This is the alternative to throwing old matches away. A hard cutoff says a
    match 91 days ago is worthless and one 89 days ago is worth full price;
    decay says neither, and keeps the rows. Use it as sample_weight when
    fitting - most scikit-learn estimators take one.
    """
    ref = reference if reference is not None else kickoffs.max()
    age_days = (ref - kickoffs).dt.total_seconds() / 86400.0
    return 0.5 ** (age_days / float(half_life_days))


def training_set(min_history=None, season="config", half_life_days=None):
    """Played matches with each side's pre-kickoff form and the real outcome.

    min_history drops rows where a team had barely any prior matches to form an
    average from - those features are noise, not signal. Raise it as the season
    fills out.

    season: "current" limits to the season config.yaml lists first, "all" uses
    every stored season, "config" (the default) follows config.yaml. Adds a
    `weight` column - recency weights, not a feature. Pass it as sample_weight;
    feature_columns() excludes it.
    """
    cfg = training_config()
    if season == "config":
        season = cfg["season"]
    if min_history is None:
        min_history = cfg["min_history"]
    if half_life_days is None:
        half_life_days = cfg["half_life_days"]

    sql = """
        SELECT * FROM v_match_features
        WHERE home_matches_before >= %(n)s AND away_matches_before >= %(n)s
    """
    params = {"n": min_history}
    if season and season != "all":
        params["season"] = current_season() if season == "current" else str(season)
        sql += " AND season = %(season)s"
    sql += " ORDER BY kickoff"

    sql = sql.replace("ORDER BY kickoff",
                      f"AND {TARGET} IS NOT NULL ORDER BY kickoff")
    df = pd.read_sql(sql, engine(), params=params, parse_dates=["kickoff"])
    df["weight"] = (decay_weights(df["kickoff"], half_life_days)
                    if len(df) else pd.Series(dtype="float64"))
    return df


def baselines(train, target=TARGET):
    """What a model has to beat, in mean absolute error (percentage points).

    Regression needs a reference the way a classifier needs the majority class.
    Three, in increasing order of difficulty:

      always_50      - possession is zero-sum, so 50 is the unconditional mean
                       and this is the "know nothing" floor.
      home_form      - predict the home side's own recent average, ignoring who
                       they are playing.
      naive_midpoint - split the difference between what the home side usually
                       takes and what the away side usually concedes. This is
                       the one that matters: it is nearly free to compute, and
                       a model that cannot beat it is not earning its keep.
    """
    if not len(train):
        return {}
    y = train[target]
    out = {"always_50": (y - 50).abs().mean()}
    if "home_poss_l5" in train:
        out["home_form"] = (y - train["home_poss_l5"]).abs().mean()
    if "poss_naive_l5" in train:
        out["naive_midpoint"] = (y - train["poss_naive_l5"]).abs().mean()
    return {k: float(v) for k, v in out.items() if pd.notna(v)}


def fixtures():
    """Upcoming matches, same feature names as the training set."""
    return pd.read_sql("SELECT * FROM v_fixture_features ORDER BY kickoff",
                       engine(), parse_dates=["kickoff"])


def feature_columns(train, upcoming):
    """Columns usable as model inputs: numeric, and present on BOTH sides.

    A feature that exists only in training cannot be used to predict, so it has
    to be excluded up front rather than discovered at scoring time.
    """
    identifiers = {
        "match_id", "kickoff", "season", "match_week", "period",
        "home_team_id", "away_team_id", "home_team", "away_team",
        "home_score", "away_score", "outcome", "total_goals",
        "home_prev_competition", "away_prev_competition",
        # Recency weight: numeric, and present only on the training side. It
        # would sail through the numeric check below and hand the model a
        # column that encodes how recent the match is.
        "weight",
        # The targets.
        "home_possession", "away_possession",
        # Post-match context. These are numeric and would pass every check
        # below, but minutes spent ahead or behind are only known once the
        # match is over. Feeding them to a model that predicts possession is
        # leakage, and would look like a brilliant model right up to the point
        # you tried to predict a fixture that had not kicked off.
        "home_minutes_ahead_post", "home_minutes_level_post",
        "home_minutes_behind_post",
    }
    return [c for c in train.columns
            if c in upcoming.columns
            and c not in identifiers
            and pd.api.types.is_numeric_dtype(train[c])]


def time_split(train, holdout=0.2):
    """Split by date, never at random.

    A random split lets the model learn from matches played after the ones it
    is scored on - the same leak the form windows are designed to avoid,
    reintroduced at the last step.
    """
    cut = int(len(train) * (1 - holdout))
    return train.iloc[:cut].copy(), train.iloc[cut:].copy()


if __name__ == "__main__":
    tr = training_set()
    up = fixtures()
    feats = feature_columns(tr, up)
    a, b = time_split(tr)
    print(f"target         : {TARGET}")
    print(f"training rows  : {len(tr)}")
    print(f"fixtures       : {len(up)}")
    print(f"usable features: {len(feats)}")
    print(f"time split     : {len(a)} fit / {len(b)} holdout")
    if len(tr):
        print(f"target range   : {tr[TARGET].min():.1f} - {tr[TARGET].max():.1f}"
              f"  (mean {tr[TARGET].mean():.1f})")
        print("baselines (mean absolute error, percentage points):")
        for name, mae in sorted(baselines(tr).items(), key=lambda kv: -kv[1]):
            print(f"    {name:16} {mae:.2f}")
