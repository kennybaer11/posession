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


def measure(competition):
    """Walk-forward residuals for one league, or None if too few to trust."""
    import numpy as np
    import load
    import model

    train = load.training_set(season="all", competition=competition,
                              min_history=FIT_MIN_HISTORY)
    feats = model.available_features(train)
    if len(train) <= MIN_FIT_ROWS or not feats:
        return None
    bt = model.walk_forward(train, feats, min_train=MIN_FIT_ROWS)
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

    for comp in leagues:
        row = measure(comp)
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
