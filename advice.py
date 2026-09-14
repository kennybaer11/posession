"""Freeze the site's current advice for every line that has not kicked off.

    python advice.py            record it
    python advice.py --dry-run  show what would be recorded

Runs in both workflows just before the site is rendered, from the same data
and the same model, so what is stored is what the pages published in that
run. See pl_advice in db.py for why this exists and how it stays frozen.

The advice comes from app._line_rows - the function the Model, Fixtures and
Learning pages render from - rather than being recomputed here. A second copy
of the arithmetic could quietly disagree with the pages, and then the record
would not be the advice the site gave.
"""

import argparse
import logging
import os
import subprocess
import sys

log = logging.getLogger("advice")


def code_version():
    """The commit the advice was computed with, so a record can be traced."""
    sha = os.getenv("GITHUB_SHA")
    if sha:
        return sha[:12]
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"],
                              capture_output=True, text=True, check=True,
                              cwd=os.path.dirname(os.path.abspath(__file__))
                              ).stdout.strip() or None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Freeze current advice.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    import app as webapp
    from db import Database

    db = Database()
    db.ensure_schema(with_views=False)
    with db.conn.cursor() as cur:
        cur.execute("SELECT now() AT TIME ZONE 'UTC' AS now")
        now = cur.fetchone()["now"]

    with webapp.app.test_request_context("/"):
        rows, _ = webapp._line_rows(webapp.ALL)

    version = code_version()
    pending = []
    for r in rows:
        if r["actual"] is not None or r["kickoff"] <= now:
            continue                    # played or started: never (re)advised
        if r["pred"] is None:
            continue                    # no prediction, nothing was advised
        pending.append({
            "match_id": r["match_id"], "bookmaker": "chance.cz",
            "competition": r["competition"], "kickoff": r["kickoff"],
            "team_id": r["team_id"], "line": r["line"],
            "over_odds": r["over_odds"], "under_odds": r["under_odds"],
            "pred": round(float(r["pred"]), 2),
            "sigma": r["sigma"], "p_over": r["p_over"],
            "side": r["side"], "odds": r["odds"], "edge": r["edge"],
            "rating": r["rating"], "backed": bool(r["backed"]),
            "fallback": bool(r["fallback"]), "why": r["why"],
            "code_version": version,
        })

    for p in pending:
        log.info("  %s  %-10s line %5.1f  %-6s edge %s  %s/10%s",
                 p["kickoff"].strftime("%d %b %H:%M"), p["competition"],
                 p["line"], p["side"] or "no bet",
                 f"{p['edge']:+.1%}" if p["edge"] is not None else "   -",
                 p["rating"], "  (fallback)" if p["fallback"] else "")
    if args.dry_run:
        log.info("dry run: %d line(s) would be recorded", len(pending))
        db.close()
        return 0

    written, refused = db.freeze_advice(pending)
    log.info("Advice recorded for %d upcoming line(s); %d refused as already "
             "kicked off. Code %s.", written, refused, version)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
