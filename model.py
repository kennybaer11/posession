"""Predict home possession, and turn that into a betting decision.

    python model.py                       # backtest + what it says about fixtures
    python model.py --line 54.5 --under 1.94 --match 2645216

A point estimate is not a bet. A bookmaker offering "Arsenal over/under 54.5%"
is quoting a PROBABILITY, so beating it needs a calibrated distribution, not a
good guess at the number. Everything here is built around that distinction:

  1. fit a model                -> a mean
  2. measure its errors honestly -> a spread around that mean
  3. mean + spread              -> P(possession > line)
  4. compare with the odds      -> edge, and only then a stake

Step 2 is the one that decides whether any of this is worth acting on, and it
is the one that is easiest to fool yourself about.
"""

import argparse
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

import load

# Deliberately few. With a season's worth of rows the full feature set has more
# columns than examples, and ridge alone will not save a model from that. These
# are the columns with a real mechanism behind them rather than a correlation.
CORE_FEATURES = [
    "poss_naive_l5",      # the midpoint of what home takes and away concedes
    "poss_gap_l5",        # possession is relative before it is absolute
    "home_poss_l10", "away_poss_l10",
    "home_poss_l20", "away_poss_l20",
    "home_poss_home_l5", "away_poss_away_l5",
    "home_pass_acc_l5", "away_pass_acc_l5",
]


class NaiveMidpoint:
    """Predict (home form + what the away side concedes) / 2, plus a bias term.

    This is the default because it wins. Measured over 334 walk-forward
    matches, ridge on ten possession columns scored 7.88 mean absolute error
    against this estimator's 6.80, and every feature set and regularisation
    strength tried came out worse - monotonically worse as alpha rose, which is
    the tell: shrinking toward the training mean destroys exactly the
    team-to-team variation that possession is made of.

    The formula already encodes the right structure. Possession is zero-sum, so
    what one side takes the other concedes, and the midpoint of the two claims
    is the natural estimate. A linear model given the same information can only
    blur it.

    The bias term corrects a real, consistent tendency: actual possession comes
    in about 1 point above this estimate, because the fitted window includes
    matches against opponents who are not the one being faced.
    """

    def __init__(self, bias=0.0):
        self.bias = bias

    def fit(self, X, y=None, **kw):
        pred = X["poss_naive_l5"]
        if y is not None:
            mask = pred.notna() & pd.Series(y, index=X.index).notna()
            if mask.any():
                self.bias = float((pd.Series(y, index=X.index)[mask]
                                   - pred[mask]).mean())
        return self

    def predict(self, X):
        return (X["poss_naive_l5"] + self.bias).to_numpy(dtype=float)


def build(alpha=10.0):
    """Ridge on standardised features, with median imputation.

    Ridge rather than anything fancier because the sample is small and the
    relationships are close to linear: possession is largely a stable team
    trait, and the useful signal is which of two sides usually has more of it.
    A gradient booster would find more structure in this many rows than
    actually exists.
    """
    return make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        Ridge(alpha=alpha),
    )


def available_features(df, wanted=None):
    return [c for c in (wanted or CORE_FEATURES) if c in df.columns]


def make(estimator, alpha=10.0):
    """The default is the naive midpoint - see NaiveMidpoint for why."""
    return NaiveMidpoint() if estimator == "naive" else build(alpha)


def walk_forward(train, feats, min_train=8, alpha=10.0, estimator="naive"):
    """Refit before every match, predicting only ever forwards.

    A single train/test split reports one number that depends heavily on where
    the split fell. Refitting at each step uses every match as a test case
    exactly once while never letting the model see its own future - the same
    discipline the feature windows enforce, applied to evaluation.

    Returns the out-of-sample predictions, which are what any honest error
    estimate has to be built from.
    """
    y = train[load.TARGET].to_numpy(dtype=float)
    X = train[feats]
    rows = []
    for i in range(min_train, len(train)):
        model = make(estimator, alpha)
        if estimator == "naive":
            model.fit(train.iloc[:i], y[:i])
        else:
            model.fit(X.iloc[:i], y[:i],
                      ridge__sample_weight=train["weight"].to_numpy()[:i])
        frame = train.iloc[[i]] if estimator == "naive" else X.iloc[[i]]
        rows.append({
            "kickoff": train["kickoff"].iloc[i],
            "home_team": train["home_team"].iloc[i],
            "away_team": train["away_team"].iloc[i],
            "actual": y[i],
            "predicted": float(model.predict(frame)[0]),
            "naive": float(train["poss_naive_l5"].iloc[i])
                     if "poss_naive_l5" in train else np.nan,
        })
    return pd.DataFrame(rows)


def residual_sigma(backtest):
    """Spread of the out-of-sample errors - the width of the distribution.

    This is the number that decides whether a bet is ever worth making, and
    the one most easily understated. Taken from walk-forward predictions, not
    from the training fit, because a model's error on data it has already seen
    says nothing about the error on a match that has not been played.
    """
    if not len(backtest):
        return float("nan")
    return float((backtest["actual"] - backtest["predicted"]).std(ddof=1))


def prob_over(mean, sigma, line):
    """P(possession > line), assuming errors are roughly normal.

    Possession is bounded [0, 100] and mildly skewed, so this is an
    approximation - but with sigma near 10 and lines near 50 the normal tail is
    close enough that model error, not distributional shape, is what dominates.
    """
    if not sigma or math.isnan(sigma) or sigma <= 0:
        return float("nan")
    from scipy.stats import norm
    return float(1.0 - norm.cdf(line, loc=mean, scale=sigma))


# -- odds -------------------------------------------------------------------

def implied(odds):
    """Decimal odds -> the probability the price implies (margin included)."""
    return 1.0 / float(odds)


def devig(odds_a, odds_b):
    """Strip the bookmaker's margin from a two-way market.

    Implied probabilities on both sides of an over/under sum to more than 1 -
    that excess is the margin, and it is what you are actually up against.
    Scaling both to sum to 1 gives the bookmaker's real opinion, which is the
    thing worth comparing a model against.
    """
    a, b = implied(odds_a), implied(odds_b)
    total = a + b
    return a / total, b / total, total - 1.0


def kelly(p, odds):
    """Fraction of bankroll Kelly says to stake. Negative means do not bet.

    f = (p*(odds-1) - (1-p)) / (odds-1)

    Full Kelly is famously aggressive and assumes p is exactly right. When p
    comes from a model fitted on a few dozen matches, it is not - so the
    fraction returned here is meant to be scaled down hard, not followed.
    """
    b = float(odds) - 1.0
    if b <= 0:
        return 0.0
    return (p * b - (1.0 - p)) / b


# How many settled bets the model has actually been graded on, and the highest
# stake rating that record can justify. An edge estimate is only as trustworthy
# as the evidence that the model can find edges at all, and right now that
# evidence is one settled selection. The ladder is deliberately steep at the
# bottom: going from "no record" to "a handful of wins" should barely move the
# stake, because a handful of wins is what luck looks like.
EVIDENCE_LADDER = (
    (10,   1, "almost no track record"),
    (25,   2, "a very thin track record"),
    (50,   3, "a thin track record"),
    (100,  5, "a short track record"),
    (200,  7, "a moderate track record"),
    (10**9, 10, "a substantial track record"),
)


def evidence_cap(n_settled):
    """Ceiling on the stake rating, from how much the model has been graded on."""
    for threshold, cap, label in EVIDENCE_LADDER:
        if n_settled < threshold:
            return cap, label
    return 10, "a substantial track record"


def verdict(results):
    """Should you be betting this model yet? A rule, not an opinion.

    `results` is a list of (won, odds) for every settled bet the model actually
    backed. The question is not "did it profit" - over a handful of bets that is
    mostly luck - but "has it profited by more than luck can explain".

    Each bet at odds o needs a win rate of 1/o to break even, so the breakeven
    for a mixed set is the average of those. Against that we test the observed
    rate, using the standard error of a proportion. Two standard errors clear of
    breakeven is the usual bar for calling a result real, and it is a high one:
    at typical possession-market prices it means roughly 100-200 settled bets.

    That number is not pessimism. It is what it costs to distinguish a genuine
    5% edge from a coin that happened to land well, and no amount of confidence
    in the model shortens it.
    """
    n = len(results)
    if n == 0:
        return {"n": 0, "ready": False,
                "reason": "no settled bets yet - nothing has been tested"}

    wins = sum(1 for won, _ in results if won)
    breakeven = sum(implied(o) for _, o in results) / n
    rate = wins / n
    profit = sum((o - 1) if won else -1 for won, o in results)

    se = math.sqrt(max(breakeven * (1 - breakeven), 1e-9) / n)
    z = (rate - breakeven) / se if se else 0.0

    # How many bets at the CURRENT rate before the result would clear 2 SE.
    needed = None
    if rate > breakeven:
        gap = rate - breakeven
        needed = int(math.ceil(4 * breakeven * (1 - breakeven) / (gap ** 2)))

    ready = n >= 50 and z >= 2
    if ready:
        reason = (f"{wins}/{n} at {rate:.0%} against a {breakeven:.0%} "
                  f"breakeven - {z:.1f} standard errors clear, which luck "
                  f"does not explain")
    elif n < 50:
        reason = (f"only {n} settled bet{'' if n == 1 else 's'}. Below about 50 "
                  f"the result is noise whichever way it falls")
    elif rate <= breakeven:
        reason = (f"{wins}/{n} at {rate:.0%}, below the {breakeven:.0%} "
                  f"breakeven - the model is losing to the price")
    else:
        reason = (f"{wins}/{n} at {rate:.0%} against {breakeven:.0%} breakeven, "
                  f"but only {z:.1f} standard errors clear"
                  + (f"; about {needed} settled bets at this rate would settle it"
                     if needed else ""))

    return {"n": n, "wins": wins, "rate": rate, "breakeven": breakeven,
            "profit": profit, "z": z, "ready": ready, "needed": needed,
            "reason": reason}


def choose_side(p_over, over_odds, under_odds, n_settled=0):
    """With both prices quoted, work out which side (if either) to back.

    Each side is judged against its own price, and the better one wins. Usually
    at most one can be positive: the bookmaker's margin means the two implied
    probabilities sum to more than 1, so a genuine edge on both sides would
    mean the market is priced wrongly in both directions at once - possible,
    but far more often a sign the model is wrong.

    Returns (side, probability, edge, rating, why). side is None when neither
    price is worth taking, which is the common and correct answer.
    """
    options = []
    if over_odds:
        options.append(("OVER", p_over, float(over_odds)))
    if under_odds:
        options.append(("UNDER", 1.0 - p_over, float(under_odds)))
    if not options:
        return None, None, None, 0, "no price recorded"

    best = max(options, key=lambda o: o[1] - implied(o[2]))
    side, p, odds = best
    edge = p - implied(odds)
    if edge <= 0:
        # Say how close the better side came, so "no bet" is informative
        # rather than just a shrug.
        return (None, p, edge, 0,
                f"best side is {side} at {odds:.2f}, still {abs(edge):.1%} "
                f"short of its {implied(odds):.1%} breakeven")
    rating, why = stake_rating(p, odds, n_settled)
    return side, p, edge, rating, why


def stake_rating(p, odds, n_settled=0, kelly_fraction=0.25):
    """A 0-10 stake, and an honest account of what is limiting it.

    Two independent things have to be true before staking much: the edge must
    be large, AND the model must have shown it can find real edges. The first
    is arithmetic; the second is a track record, and no amount of confidence in
    a single number substitutes for it.

    So the rating is the smaller of an edge score and an evidence cap. A 20%
    edge on a model with one settled bet is not a 10 - it is a 1 with an
    interesting hypothesis attached.
    """
    if p is None or not odds:
        return 0, "no price"
    edge = p - implied(odds)
    if edge <= 0:
        return 0, "no edge - the price is against you"

    # Quarter Kelly is the practical ceiling for a model of uncertain quality,
    # so map 0 -> 0.25 of bankroll onto 0 -> 10.
    f = kelly(p, odds) * kelly_fraction
    edge_score = max(1, min(10, round(f / 0.025)))

    cap, label = evidence_cap(n_settled)
    if cap < edge_score:
        return cap, (f"edge alone suggests {edge_score}/10, capped at {cap} by "
                     f"{label} ({n_settled} settled)")
    return edge_score, f"edge of {edge:+.1%} at {odds:.2f}"


def assess(mean, sigma, line, over_odds=None, under_odds=None, bankroll=None,
           kelly_fraction=0.25):
    """Everything needed to decide, in one dict."""
    p_over = prob_over(mean, sigma, line)
    p_under = 1.0 - p_over if not math.isnan(p_over) else float("nan")
    out = {"mean": mean, "sigma": sigma, "line": line,
           "p_over": p_over, "p_under": p_under}

    if over_odds and under_odds:
        fair_over, fair_under, margin = devig(over_odds, under_odds)
        out.update({"book_p_over": fair_over, "book_p_under": fair_under,
                    "margin": margin})
    for side, p, odds in (("over", p_over, over_odds),
                          ("under", p_under, under_odds)):
        if not odds:
            continue
        f = kelly(p, odds)
        out[f"{side}_odds"] = float(odds)
        out[f"{side}_breakeven"] = implied(odds)
        out[f"{side}_edge"] = p - implied(odds)
        out[f"{side}_ev"] = p * (float(odds) - 1.0) - (1.0 - p)
        out[f"{side}_kelly"] = f
        out[f"{side}_stake"] = (max(f, 0.0) * kelly_fraction * bankroll
                                if bankroll else None)
    return out


def main():
    ap = argparse.ArgumentParser(description="Possession model and bet check.")
    ap.add_argument("--season", default="config",
                    help='"current", "all", a year, or "config"')
    ap.add_argument("--alpha", type=float, default=10.0)
    ap.add_argument("--estimator", choices=("naive", "ridge"), default="naive",
                    help="naive (default, and better) or ridge")
    ap.add_argument("--line", type=float, help="the over/under line, e.g. 54.5")
    ap.add_argument("--over", type=float, help="decimal odds for OVER")
    ap.add_argument("--under", type=float, help="decimal odds for UNDER")
    ap.add_argument("--match", help="match_id to assess")
    ap.add_argument("--bankroll", type=float)
    args = ap.parse_args()

    train = load.training_set(season=args.season)
    upcoming = load.fixtures()
    feats = available_features(train)

    print(f"target        : {load.TARGET}   estimator: {args.estimator}")
    print(f"training rows : {len(train)}   features: {len(feats)}")
    if len(train) < 12:
        print("WARNING: too few rows for the backtest below to mean much.")

    bt = walk_forward(train, feats, alpha=args.alpha,
                      estimator=args.estimator)
    if not len(bt):
        print("\nNot enough rows to walk forward. Widen training.season.")
        return 1

    sigma = residual_sigma(bt)
    mae = float((bt["actual"] - bt["predicted"]).abs().mean())
    mae_naive = float((bt["actual"] - bt["naive"]).abs().mean())

    print(f"\nWalk-forward over {len(bt)} out-of-sample match(es):")
    print(f"  model MAE          {mae:.2f} points")
    print(f"  naive midpoint MAE {mae_naive:.2f} points")
    print(f"  beats naive by     {mae_naive - mae:+.2f} points")
    print(f"  residual sigma     {sigma:.2f} points")

    if args.line and args.match:
        row = upcoming[upcoming.match_id.astype(str) == str(args.match)]
        if not len(row):
            print(f"\nNo upcoming fixture with match_id {args.match}")
            return 1
        model = make(args.estimator, args.alpha)
        if args.estimator == "naive":
            model.fit(train, train[load.TARGET])
            mean = float(model.predict(row)[0])
        else:
            model.fit(train[feats], train[load.TARGET],
                      ridge__sample_weight=train["weight"])
            mean = float(model.predict(row[feats])[0])
        r = row.iloc[0]
        print(f"\n{r.home_team} v {r.away_team}  ({r.kickoff:%d %b %H:%M})")
        res = assess(mean, sigma, args.line, args.over, args.under,
                     args.bankroll)
        print(f"  predicted home possession {res['mean']:.1f}% "
              f"(sigma {res['sigma']:.1f})")
        print(f"  P(over {args.line})  {res['p_over']:.1%}")
        print(f"  P(under {args.line}) {res['p_under']:.1%}")
        for side in ("over", "under"):
            if f"{side}_odds" in res:
                print(f"  {side.upper():5} @ {res[f'{side}_odds']:.2f}  "
                      f"breakeven {res[f'{side}_breakeven']:.1%}  "
                      f"edge {res[f'{side}_edge']:+.1%}  "
                      f"EV {res[f'{side}_ev']:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
