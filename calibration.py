"""How wide each league's prediction errors really are, measured and stored.

    python calibration.py            measure every league and store it
    python calibration.py --dry-run  measure and print, store nothing

Every probability the site shows - P(over), the edge, the stake - comes from a
normal distribution around the prediction, and sigma is its width. One sigma
for all three leagues was wrong in both directions: measured walk-forward it is
about 8.0 in the Premier League, 8.7 in LaLiga and 6.6 in the Bundesliga. With
a shared 8.02, LaLiga's edges were overstated and the Bundesliga's understated.

Measuring takes around half a minute, too slow for every page render, so it
runs in the data workflow before the site is rebuilt and the result is stored
in pl_model_calibration. The app reads the stored value and falls back to
DEFAULT_SIGMA for a league without enough history to measure honestly.

Deliberately free of heavy imports at module level: app.py reads the constants
below and must not pull in scikit-learn just to start.
"""

import argparse
import logging
import sys

log = logging.getLogger("calibration")

# Below this many training rows a league falls back to the naive midpoint.
# Roughly four rows per feature - a rule of thumb, not a measured threshold.
MIN_FIT_ROWS = 40

# What the fit trains on, and so what anything describing the fit must count.
# Not config.yaml's min_history, which is 3 and meant for analysis.
FIT_MIN_HISTORY = 1

# The sigma used when a league has no stored calibration. 8.02 is the
# Premier League figure the site used for every league before this existed.
DEFAULT_SIGMA = 8.02

# The naive midpoint's own bias and spread, for a league on the fallback.
NAIVE_BIAS = 0.98
NAIVE_SIGMA = 8.40

# Out-of-sample errors needed before a league's own sigma replaces the default.
# A standard deviation from 30 residuals can be off by a quarter either way;
# from 100 it is within about 15%.
MIN_CALIBRATION_N = 100


def backtest():
    """One walk-forward pass over every league at once - the model the site
    actually fits since 19 Oct 2026. Returns the out-of-sample predictions
    with their league, for measure() to split."""
    import load
    import model

    train = load.training_set(season="all", competition="all",
                              min_history=FIT_MIN_HISTORY)
    feats = model.pooled_features(train)
    if len(train) <= MIN_FIT_ROWS or not feats:
        return None
    bt = model.walk_forward(train, feats, min_train=MIN_FIT_ROWS)
    bt["competition"] = train["competition"].iloc[MIN_FIT_ROWS:].to_numpy()
    bt["match_id"] = train["match_id"].iloc[MIN_FIT_ROWS:].to_numpy()
    bt["home_team_id"] = train["home_team_id"].iloc[MIN_FIT_ROWS:].to_numpy()
    return bt


# Lines needed before the shrinkage is trusted at all; under this the site
# keeps using the raw prediction and its per-league spread.
MIN_LINE_CALIBRATION = 25


def line_calibration(db, bt=None):
    """How much of the model's disagreement with a bookmaker's line comes true.

    Regresses what actually happened against what the model said, both measured
    from the line: actual - line = intercept + b * (predicted - line). b near 1
    would mean the model is right about the line as often as it claims; it came
    out at 0.74 over the first 174 settled lines, and feeding the full
    disagreement into a probability made the advice badly overconfident.

    Walk-forward predictions only - the same ones the Model page is scored on -
    so this measures the model the site runs, not a fit to its own results.
    """
    import numpy as np

    bt = backtest() if bt is None else bt
    if bt is None:
        return None
    preds = {str(r.match_id): (float(r.predicted), str(r.home_team_id))
             for r in bt.itertuples()}
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (l.match_id) l.match_id, l.team_id, l.line::float AS line,
                   tm.possession::float AS actual
              FROM pl_possession_line l
              JOIN pl_matches m ON m.match_id = l.match_id
              JOIN pl_team_match tm ON tm.match_id = l.match_id AND tm.team_id = l.team_id
             WHERE tm.possession IS NOT NULL
             ORDER BY l.match_id, l.captured_at""")
        rows = cur.fetchall()
    x, y = [], []
    for r in rows:
        hit = preds.get(str(r["match_id"]))
        if not hit:
            continue
        pred_home, home_team_id = hit
        # a line on the away side is about 100 - home possession
        flip = r["team_id"] != home_team_id
        pred = 100 - pred_home if flip else pred_home
        x.append(pred - r["line"])
        y.append(r["actual"] - r["line"])
    if len(x) < MIN_LINE_CALIBRATION:
        return None
    x, y = np.array(x), np.array(y)
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return {"scope": "all", "b": round(float(np.clip(beta[1], 0.0, 1.0)), 4),
            "intercept": round(float(beta[0]), 3),
            "sigma": round(float(resid.std(ddof=2)), 3), "n": len(x)}


def stored_line_calibration(db_query):
    """(b, intercept, sigma) for the site, or None before it is measured."""
    rows = db_query("SELECT * FROM pl_line_calibration WHERE scope = 'all'")
    if not rows or rows[0]["n"] < MIN_LINE_CALIBRATION:
        return None
    r = rows[0]
    return float(r["b"]), float(r["intercept"]), float(r["sigma"])


def measure(competition, bt=None):
    """Walk-forward residuals for one league, or None if too few to trust.

    The fit spans the leagues; the spread of its errors is still measured per
    league, because that is what the probabilities on each page are built on
    and LaLiga's errors are wider than the Bundesliga's.
    """
    import numpy as np
    import model

    bt = backtest() if bt is None else bt
    if bt is None:
        return None
    bt = bt[bt["competition"] == competition]
    if len(bt) < MIN_CALIBRATION_N:
        return None

    resid = (bt["actual"] - bt["predicted"]).to_numpy(dtype=float)
    sigma = model.residual_sigma(bt)
    naive = bt["naive"].to_numpy(dtype=float) + NAIVE_BIAS
    ok = ~np.isnan(naive)
    z = np.abs(resid) / sigma
    return {
        "competition": competition,
        "sigma": round(float(sigma), 3),
        "mae": round(float(np.abs(resid).mean()), 3),
        "naive_mae": round(float(np.abs(bt["actual"].to_numpy()[ok] - naive[ok]).mean()), 3),
        "n": int(len(bt)),
        # Share of errors inside 1, 1.645 and 1.96 sigma. A normal distribution
        # puts 68.3%, 90% and 95% there; far off either way means the sigma is
        # the right width on average but the errors are not normally shaped,
        # and the probabilities built on it are wrong in the tails.
        "within_1": round(float((z <= 1.0).mean()), 3),
        "within_164": round(float((z <= 1.645).mean()), 3),
        "within_196": round(float((z <= 1.96).mean()), 3),
    }


def stored(db_query):
    """{competition: calibration row} from whatever query function is given."""
    return {r["competition"]: r
            for r in db_query("SELECT * FROM pl_model_calibration")}


def main():
    ap = argparse.ArgumentParser(description="Measure per-league sigma.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    from dotenv import load_dotenv
    load_dotenv()
    from db import Database
    db = Database()
    db.ensure_schema(with_views=False)
    with db.conn.cursor() as cur:
        cur.execute("SELECT DISTINCT competition FROM pl_matches ORDER BY 1")
        leagues = [r["competition"] for r in cur.fetchall()]

    bt = backtest()
    cal = line_calibration(db, bt)
    if cal:
        log.info("lines   keep %.0f%% of the model's disagreement with the line, "
                 "offset %+.2f, spread %.2f, over %d settled line(s)",
                 100 * cal["b"], cal["intercept"], cal["sigma"], cal["n"])
        if not args.dry_run:
            db.ensure_connection()
            db.upsert_line_calibration(cal)
    else:
        log.info("lines   too few settled lines to measure the shrinkage yet")

    for comp in leagues:
        row = measure(comp, bt)
        if row is None:
            log.info("%-7s too little history to measure - keeping the default "
                     "%.2f", comp, DEFAULT_SIGMA)
            continue
        log.info("%-7s sigma %.3f over %d matches, MAE %.3f vs naive %.3f, "
                 "within 1/1.645/1.96 sigma %.1f/%.1f/%.1f%%",
                 comp, row["sigma"], row["n"], row["mae"], row["naive_mae"],
                 100 * row["within_1"], 100 * row["within_164"],
                 100 * row["within_196"])
        if not args.dry_run:
            db.ensure_connection()
            db.upsert_calibration(row)

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
