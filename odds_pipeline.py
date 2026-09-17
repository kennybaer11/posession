"""One command from "which matches are on" to "odds in the database".

    python odds_pipeline.py --dry-run      show what it would scrape
    python odds_pipeline.py                run it, preview the import
    python odds_pipeline.py --write        run it and write the odds

The shape of it:

  1. scrape the league pages for every match URL on offer
  2. keep the ones whose kickoff - OURS, not theirs - falls in the window
  3. scrape those match pages for the possession market
  4. resolve each to a fixture and write it

Step 2 is the one worth explaining. The scraped pages carry a kickoff time,
and it is wrong: the bookmaker renders times in the browser's timezone and
webscraper.io's cloud sits nine hours behind Prague, so "Zitra | 6:00" is a
15:00 match tomorrow. Rather than correct an offset that could change whenever
they move a server, the filter uses the kickoff times already in our database,
which came from the leagues themselves. The scrape supplies URLs; the database
supplies truth about when matches are.

Credits are the reason for the filter at all: one match page is one credit, so
scraping a whole league every run would burn a trial in days.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

API = "https://api.webscraper.io/api/v1"
LINKS_SITEMAP = int(os.getenv("WS_SITEMAP_LINKS", "1529498"))
MATCH_SITEMAP = int(os.getenv("WS_SITEMAP_MATCHES", "0") or 0)

log = logging.getLogger("odds_pipeline")


def token():
    tok = os.getenv("WEBSCRAPER_TOKEN")
    if not tok:
        raise SystemExit("WEBSCRAPER_TOKEN is not set - see .env.example")
    return tok


def _req(method, path, **kw):
    kw.setdefault("params", {})["api_token"] = token()
    kw.setdefault("timeout", 60)
    r = requests.request(method, f"{API}{path}", **kw)
    r.raise_for_status()
    return r


def start_job(sitemap_id, start_urls=None, request_interval=2000,
              page_load_delay=2000, driver="fulljs", custom_id=None):
    """Queue a scraping job.

    start_urls overrides the sitemap's own list for this run only, which is
    what makes the second stage dynamic without rewriting the saved sitemap -
    and so without a half-finished run leaving someone else's sitemap pointing
    at last week's fixtures.
    """
    body = {"sitemap_id": sitemap_id, "driver": driver,
            "page_load_delay": page_load_delay,
            "request_interval": request_interval}
    if start_urls:
        body["start_urls"] = list(start_urls)
    if custom_id:
        body["custom_id"] = custom_id
    return _req("POST", "/scraping-job", json=body).json()["data"]["id"]


def wait_for(job_id, timeout=1800, poll=15):
    """Block until a job stops running. Returns its final record."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        job = _req("GET", f"/scraping-job/{job_id}").json()["data"]
        status = job.get("status")
        if status != last:
            log.info("  job %s: %s", job_id, status)
            last = status
        if status in ("finished", "failed", "stopped"):
            return job
        time.sleep(poll)
    raise TimeoutError(f"job {job_id} still running after {timeout}s")


def job_rows(job_id):
    text = _req("GET", f"/scraping-job/{job_id}/json").text
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


# -- stage 2 selection --------------------------------------------------------

SLUG_RE = re.compile(r"/kurzy/zapas/([^/]+)/(\d+)")


def _slug_words(url):
    """The club part of a match URL, as lowercase words.

    ".../fotbal-aston-villa-nottingham/8285750/..." -> "aston villa nottingham"
    """
    m = SLUG_RE.search(url or "")
    if not m:
        return ""
    slug = m.group(1)
    slug = re.sub(r"^fotbal-", "", slug)
    return slug.replace("-", " ").lower()


# A fixture whose page has come back empty this many times is parked, unless
# kickoff is close. Three is enough to tell "not priced yet" from "never going
# to be priced" without giving up on a market that opens late.
MAX_EMPTY_ATTEMPTS = 3

# Inside this many hours of kickoff every fixture is retried regardless, because
# a market that appears at all usually appears near kickoff - and that is
# exactly when the opening price is worth having.
ALWAYS_RETRY_WITHIN_HOURS = 12

# A parked fixture is still looked at once a day. Three empty reads used to park
# it outright until its last twelve hours, which was reasonable at two runs a
# day and wrong at a run every three hours: the three reads then fell inside
# nine hours, and on 16 Sep Brentford v Chelsea was parked more than two days
# before kickoff. A market opening a day or two ahead would have been seen only
# on the morning of the match. One read a day costs a credit per parked fixture.
PARKED_RECHECK_HOURS = 24


def unpark_round(db, found_match_ids):
    """Un-park every unpriced fixture in a round where a market just opened.

    Chance opens a round's possession markets together, not one fixture at a
    time. On 16 Sep three of the Premier League's match week 5 markets appeared
    at 16:31 UTC while Brentford v Chelsea, in the same round, sat parked after
    three empty reads that morning - and stayed parked until its daily re-check
    the next morning, a day after its market had most likely opened.

    Resetting the attempt count of the round's other unpriced, not-yet-played
    fixtures makes the very next run read them. Returns how many were reset.
    """
    ids = [str(m) for m in found_match_ids]
    if not ids:
        return 0
    with db.conn.cursor() as cur:
        cur.execute("""
            UPDATE pl_odds_attempt a SET attempts = 0
            FROM pl_matches m
            WHERE a.match_id = m.match_id
              AND a.attempts > 0
              AND m.kickoff > (now() AT TIME ZONE 'UTC')
              AND NOT EXISTS (SELECT 1 FROM pl_possession_line l
                              WHERE l.match_id = m.match_id)
              AND (m.competition, m.season, m.match_week) IN (
                    SELECT competition, season, match_week FROM pl_matches
                    WHERE match_id = ANY(%s) AND match_week IS NOT NULL)
        """, (ids,))
        reset = cur.rowcount
    db.conn.commit()
    if reset:
        log.info("un-parked %d fixture(s) in the same round as a new market", reset)
    return reset


def upcoming_fixtures(db, hours, skip_priced=False, retry_all=False):
    """Fixtures kicking off within the window, from OUR data.

    skip_priced drops the ones we already hold a line for, which is what makes
    a repeat run nearly free: one match page is one credit, so re-scraping a
    fixture whose odds are already recorded spends money to learn nothing.

    Fixtures the bookmaker does not price are still included - a market can
    appear closer to kickoff - but not on every run. Chance prices some matches
    and never prices others, and the ones it never prices would otherwise cost a
    credit each, every run, to learn the same nothing. After MAX_EMPTY_ATTEMPTS
    empty reads a fixture is parked: read again once every PARKED_RECHECK_HOURS,
    and on every run once kickoff is within ALWAYS_RETRY_WITHIN_HOURS.
    retry_all ignores the parking.
    """
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT m.match_id, m.kickoff, m.competition,
                   ht.name AS home, at_.name AS away
            FROM pl_matches m
            JOIN pl_teams ht  ON ht.team_id = m.home_team_id
            JOIN pl_teams at_ ON at_.team_id = m.away_team_id
            WHERE m.kickoff BETWEEN now() AND now() + (%s * INTERVAL '1 hour')
              AND (NOT %s OR NOT EXISTS (SELECT 1 FROM pl_possession_line l
                                         WHERE l.match_id = m.match_id))
              AND (%s
                   OR m.kickoff <= now() + (%s * INTERVAL '1 hour')
                   OR COALESCE((SELECT a.attempts FROM pl_odds_attempt a
                                WHERE a.match_id = m.match_id), 0) < %s
                   OR COALESCE((SELECT a.last_attempt FROM pl_odds_attempt a
                                WHERE a.match_id = m.match_id), '-infinity')
                      < now() - (%s * INTERVAL '1 hour'))
            ORDER BY m.kickoff
        """, (hours, skip_priced, retry_all, ALWAYS_RETRY_WITHIN_HOURS,
              MAX_EMPTY_ATTEMPTS, PARKED_RECHECK_HOURS))
        return cur.fetchall()


def _norm(name):
    """Strip accents and punctuation so 'Malaga CF' matches 'malaga'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", " ", s.lower())


# Clubs the bookmaker names differently enough that no word is shared.
# Keep this as small as possible: every entry is a place the automatic match
# fails, and a silent mismatch files odds against the wrong fixture.
ALIASES = {
    "athletic club": ("bilbao",),          # Chance lists Athletic as "Bilbao"
}

# Words that appear in so many club names they identify nothing.
STOPWORDS = {"real", "club", "deportivo", "sporting", "athletic", "atletico",
             "united", "city", "borussia", "bayer", "racing"}


# Tokens that carry no identity - legal forms and generic words that appear
# across many clubs. Stripped before matching so "FC Barcelona" competes as
# "barcelona".
GENERIC = {"fc", "cf", "ud", "rcd", "rc", "sv", "tsg", "sc", "vfb", "rb",
           "de", "a", "da", "the", "afc", "cd", "ca", "club", "sad"}


def _core(name):
    """A club's identifying words, in order, without legal forms."""
    return [w for w in _norm(name).split() if w and w not in GENERIC]


def club_score(name, slug_words):
    """How well this club matches the slug: (score, position). 0 = no match.

    Tried strongest first:

      contiguous full name  "real madrid" inside "real madrid rayo vallecano"
      all words present     any order
      one distinctive word  "monchengladbach"
      prefix only           slug "hamburg" against "Hamburger SV"

    The contiguous test is what separates clubs sharing a common word. On
    "real sociedad atletico madrid", matching loose words makes Real Madrid,
    Real Betis and Atletico all plausible; only "real sociedad" and "atletico
    madrid" actually appear as phrases, which is the right answer.
    """
    key = " ".join(_norm(name).split())
    for alias in ALIASES.get(key, ()):
        if alias in slug_words:
            return 12, slug_words.index(alias)

    core = _core(name)
    if not core:
        return 0, 99
    slug = " ".join(slug_words)

    # Position is where the PHRASE begins, not where its first word first
    # occurs. "manchester united manchester city" contains "manchester" twice;
    # reporting index 0 for both clubs made home and away tie, the
    # home-before-away test rejected the real fixture, and a far weaker match
    # on "united"/"city" won instead - Newcastle v Hull.
    phrase = " ".join(core)
    if phrase:
        for i in range(len(slug_words) - len(core) + 1):
            if slug_words[i:i + len(core)] == core:
                return 10, i

    present = [w for w in core if w in slug_words]
    if present and len(present) == len(core):
        return 6, slug_words.index(present[0])

    distinctive = [w for w in core if len(w) > 3 and w not in STOPWORDS]
    for w in distinctive:
        if w in slug_words:
            return 4, slug_words.index(w)

    for w in (w for w in core if len(w) > 3):
        for i, sw in enumerate(slug_words):
            if len(sw) >= 4 and (w.startswith(sw) or sw.startswith(w)):
                return 2, i
    return 0, 99


def score_fixture(fixture, slug_words):
    """Total match quality for a fixture against one slug, or None.

    Both clubs must appear, and the home side must appear FIRST: the URL is
    built as fotbal-{home}-{away}, so order distinguishes a fixture from its
    reverse later in the season.
    """
    hs, hi = club_score(fixture["home"], slug_words)
    as_, ai = club_score(fixture["away"], slug_words)
    if not hs or not as_ or hi >= ai:
        return None
    return hs + as_


def pick_urls(link_rows, fixtures):
    """Match scraped URLs to our fixtures by the clubs named in the slug.

    Deliberately not by the scraped date - see the module docstring.

    A URL is only accepted when one fixture scores strictly better than every
    other. An ambiguous slug is reported rather than guessed at, because the
    cost of guessing wrong is odds recorded against the wrong match, which is
    invisible afterwards and poisons the one record the model is judged by.

    Two fixtures never share a URL, and no fixture is claimed twice. The second
    rule is the one that earns its keep: the league page lists matches beyond
    our window, and a URL for one of those has nothing to compete against. On
    "elche-real-madrid" the home side matched Real Sociedad on the bare prefix
    "real" and the away side matched Atletico on "madrid", scoring 6 against no
    rival - enough to file one match's odds against another. The real Real
    Sociedad v Atletico URL scores 20 on both names in full, so ranking the
    claims and keeping the best resolves it without needing a score threshold.
    """
    urls = []
    for r in link_rows:
        for key in ("match_links-href", "match_links", "web-scraper-start-url"):
            u = r.get(key)
            if u and "/kurzy/zapas/" in str(u):
                urls.append(str(u))
                break

    claims, unmatched, ambiguous, superseded = [], [], [], []
    for url in dict.fromkeys(urls):           # de-dupe, keep order
        words = _slug_words(url).split()
        if not words:
            continue
        scored = [(score_fixture(f, words), f) for f in fixtures]
        scored = sorted(((s, f) for s, f in scored if s), key=lambda x: -x[0])
        if not scored:
            unmatched.append(url)
        elif len(scored) > 1 and scored[0][0] == scored[1][0]:
            ambiguous.append((url, [f["home"] + " v " + f["away"]
                                    for _, f in scored[:3]]))
        else:
            claims.append((scored[0][0], url, scored[0][1]))

    # One fixture, one URL: strongest claim wins, the rest are reported as
    # losers rather than silently dropped, because a fixture attracting two
    # URLs usually means the slug vocabulary needs an alias, not a stronger
    # filter.
    chosen, seen = [], {}
    for score, url, fix in sorted(claims, key=lambda c: -c[0]):
        key = fix["match_id"]
        if key in seen:
            superseded.append((url, fix["home"] + " v " + fix["away"],
                               score, seen[key]))
            continue
        seen[key] = score
        chosen.append((url, fix))
    return chosen, unmatched, ambiguous, superseded


def main():
    ap = argparse.ArgumentParser(description="Scrape and import possession odds.")
    ap.add_argument("--hours", type=int, default=48,
                    help="how far ahead to look for fixtures (default 48)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show which matches would be scraped, spend nothing")
    ap.add_argument("--skip-priced", action="store_true",
                    help="ignore fixtures whose odds are already recorded, so "
                         "a repeat run only pays for what is missing")
    ap.add_argument("--retry-all", action="store_true",
                    help="also re-read fixtures parked after repeated empty "
                         "reads, which normally wait until kickoff is near")
    ap.add_argument("--write", action="store_true",
                    help="write the odds (otherwise the import is a preview)")
    ap.add_argument("--links-job", type=int,
                    help="reuse a finished stage-1 job instead of running one")
    ap.add_argument("--matches-job", type=int,
                    help="reuse a finished stage-2 job: re-runs the import "
                         "against a scrape already paid for")
    ap.add_argument("--matches-sitemap", type=int, default=MATCH_SITEMAP,
                    help="sitemap id for the match-detail scrape")
    ap.add_argument("--interval", type=int, default=2000,
                    help="ms between requests (be polite)")
    ap.add_argument("--wait-budget", type=float, default=35,
                    help="minutes to wait for webscraper.io in total before "
                         "stopping cleanly as 'timeout' - keep it under the "
                         "workflow step's own time limit, or the step is "
                         "killed first and nothing is recorded")
    ap.add_argument("--min-gap-hours", type=float, default=0,
                    help="skip entirely if a run started within this many "
                         "hours - lets two schedules share one budget")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    from db import Database
    db = Database()
    db.ensure_schema(with_views=False)

    # Free work first: odds from an earlier run that timed out or was killed,
    # whose scrape has since finished on webscraper.io. Before the gap check,
    # because the gap exists to save credits and this spends none.
    if args.write and not (args.links_job or args.matches_job or args.dry_run):
        try:
            recover_unfinished(db)
        except Exception:
            # Recovery is a bonus. A bug in it must never cost the scrape that
            # follows - that would turn one lost market into a lost hour.
            log.exception("recovery failed - carrying on with the scrape")
            db.ensure_connection()

    if args.min_gap_hours:
        recent = recent_run(db, args.min_gap_hours)
        if recent:
            # Recorded, not silent. A skip used to leave no row, which made
            # three and a half hours without a single look at the bookmaker
            # invisible on 16 Sep. The Scraper page shows skips muted, so they
            # explain gaps without burying the runs that did the work.
            reason = (f"skipped: a run started {recent['started_at']:%H:%M} UTC "
                      f"({recent['source']}), within {args.min_gap_hours:g}h")
            log.info("%s", reason)
            skip = db.start_run(
                source="github-actions" if os.getenv("GITHUB_ACTIONS") else "local",
                hours=args.hours, skip_priced=bool(args.skip_priced))
            db.finish_run(skip, status="skipped", detail=reason)
            db.close()
            return 0

    # Opened before anything is scraped, so a run that dies mid-way still
    # leaves a row. GITHUB_ACTIONS is set by the runner and nothing else.
    run_id = db.start_run(
        source="github-actions" if os.getenv("GITHUB_ACTIONS") else "local",
        hours=args.hours, skip_priced=bool(args.skip_priced),
        # Re-importing a finished stage-2 job opens no pages, so costs nothing.
        reused_jobs=bool(args.matches_job))
    try:
        return _run(args, db, run_id)
    except Exception as exc:
        import traceback
        db.finish_run(run_id, status="error",
                      detail=traceback.format_exc()[-2000:])
        log.error("run failed: %s", exc)
        raise
    finally:
        db.close()


# Statuses that mean a run genuinely happened and should hold off the next one.
# preview and dry-run are hand-run experiments that wrote nothing, and error is
# a run that failed - none of those should stop a real run from trying.
_COUNTS_AS_RUN = ("ok", "ok-with-problems", "idle", "timeout", "recovered")

# A 'running' row older than this is a process that died without reporting, not
# a run in progress - it must not block the schedule forever.
_RUNNING_STALE_MINUTES = 60


def recent_run(db, hours):
    """The latest run that should hold off another, or None.

    Exists because two GitHub workflows now attempt the odds scrape: the odds
    workflow's own four slots, and a step inside the data workflow. GitHub
    fires both unreliably - hours late, often not at all - so between them
    there are more chances than either gives alone. Without a gap they would
    also spend twice when both happen to land close together.
    """
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT started_at, source, status FROM pl_scrape_run
            WHERE started_at > now() - (%s * INTERVAL '1 hour')
              AND NOT reused_jobs
              AND (status = ANY(%s)
                   OR (status = 'running'
                       AND started_at > now() - (%s * INTERVAL '1 minute')))
            ORDER BY started_at DESC LIMIT 1
        """, (hours, list(_COUNTS_AS_RUN), _RUNNING_STALE_MINUTES))
        return cur.fetchone()


class WaitBudgetExceeded(Exception):
    pass


def recover_unfinished(db):
    """Import the odds from earlier runs that stopped before importing them.

    On 16 Sep webscraper.io queued a run's first stage for 17 minutes, the
    workflow killed the step at its time limit mid-wait, and the scrape it had
    paid for - Levante v Athletic's market included - was never imported. The
    next run then skipped, because the dead run still looked in progress.

    Runs now record their job ids as soon as each job is queued, and stop with
    status 'timeout' before the step limit. This picks those up: a job that has
    since finished is imported, lines for matches that have already kicked off
    are dropped (a price read after kickoff is not an opening line), and the run
    is marked recovered. A job still running is left for the next run. A failed
    job is marked recovered with nothing imported, so it is not retried forever.
    """
    import odds_sheet
    import import_odds as io_mod
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT run_id, started_at, status, stage2_job FROM pl_scrape_run
            WHERE NOT recovered AND NOT reused_jobs AND stage2_job IS NOT NULL
              AND started_at > now() - INTERVAL '24 hours'
              AND (status IN ('timeout', 'error')
                   OR (status = 'running'
                       AND started_at < now() - (%s * INTERVAL '1 minute')))
            ORDER BY started_at""", (_RUNNING_STALE_MINUTES,))
        pending = cur.fetchall()
    for run in pending:
        try:
            job = _req("GET", f"/scraping-job/{run['stage2_job']}").json()["data"]
        except Exception as exc:
            log.warning("recovery: cannot read job %s: %s", run["stage2_job"], exc)
            continue
        status = job.get("status")
        if status not in ("finished", "failed", "stopped"):
            log.info("recovery: run %s's job %s is still %s - next run will retry",
                     run["run_id"], run["stage2_job"], status)
            continue
        if status != "finished":
            db.finish_run(run["run_id"], status=run["status"], recovered=True,
                          detail=f"job {run['stage2_job']} {status} - nothing to recover")
            continue

        rows = job_rows(run["stage2_job"])
        db.ensure_connection()
        ready, problems = io_mod.resolve_rows(db, odds_sheet.parse_webscraper(rows))
        fresh = []
        with db.conn.cursor() as cur:
            cur.execute("SELECT now() AT TIME ZONE 'UTC' AS now")
            now = cur.fetchone()["now"]
            for r in ready:
                cur.execute("SELECT kickoff FROM pl_matches WHERE match_id = %s",
                            (r["match_id"],))
                ko = cur.fetchone()
                if ko and ko["kickoff"] > now:
                    fresh.append(r)
        late = len(ready) - len(fresh)
        for r in fresh:
            r.pop("_label", None)
            r.pop("_flipped", None)
        written = db.upsert_lines(fresh)
        found = {r["match_id"] for r in fresh}
        db.record_attempts(list(found), found)
        unpark_round(db, found)
        detail = (f"recovered from job {run['stage2_job']}: {written} line(s) written"
                  + (f", {late} dropped as already kicked off" if late else "")
                  + (f"; problems: {'; '.join(map(str, problems))}" if problems else ""))
        log.info("recovery: run %s - %s", run["run_id"], detail)
        db.finish_run(run["run_id"], status="recovered", recovered=True,
                      rows_back=len(rows), resolved=len(ready),
                      problems=len(problems), written=written, detail=detail[:2000])


def credits_left():
    """Remaining page credits, or None if the account cannot be read.

    Recorded per run so the Scraper page can show what each one cost without
    the page itself needing the API token.
    """
    try:
        return _req("GET", "/account").json()["data"]["page_credits"]
    except Exception:
        return None


def _run(args, db, run_id):
    deadline = time.time() + args.wait_budget * 60
    try:
        return _run_stages(args, db, run_id, deadline)
    except WaitBudgetExceeded as exc:
        # A clean stop, not a failure: the job ids are already on the row, and
        # the next run imports the scrape once webscraper.io finishes it.
        log.warning("%s - stopping; the next run will recover it", exc)
        db.finish_run(run_id, status="timeout", detail=str(exc)[:2000])
        return 0


def _wait(job_id, deadline, stage):
    remaining = deadline - time.time()
    if remaining <= 0:
        raise WaitBudgetExceeded(f"no time left to wait for {stage} job {job_id}")
    try:
        return wait_for(job_id, timeout=remaining)
    except TimeoutError:
        raise WaitBudgetExceeded(
            f"{stage} job {job_id} still running when the wait budget ran out "
            f"- webscraper.io is queueing slowly")


def _run_stages(args, db, run_id, deadline):
    fixtures = upcoming_fixtures(db, args.hours, args.skip_priced,
                                 args.retry_all)
    log.info("%d fixture(s) kicking off in the next %dh%s", len(fixtures),
             args.hours, " without odds" if args.skip_priced else "")
    for f in fixtures[:12]:
        log.info("   %s  %s v %s  [%s]", f["kickoff"].strftime("%d %b %H:%M"),
                 f["home"][:22], f["away"][:22], f["competition"])
    if not fixtures:
        log.info("Nothing due - stopping before spending any credits.")
        db.finish_run(run_id, fixtures=0, pages=0, written=0,
                      status="idle", detail="no fixtures in the window")
        return 0

    # -- stage 1: which match pages exist --------------------------------
    if args.links_job:
        links_job = args.links_job
        log.info("reusing stage-1 job %s", links_job)
    elif args.dry_run:
        log.info("dry run: would start stage-1 job on sitemap %s", LINKS_SITEMAP)
        db.finish_run(run_id, fixtures=len(fixtures), status="dry-run")
        return 0
    else:
        links_job = start_job(LINKS_SITEMAP, request_interval=args.interval,
                              custom_id="stage1-links")
        log.info("stage 1 queued as job %s", links_job)
        db.note_run(run_id, stage1_job=str(links_job), fixtures=len(fixtures))
        _wait(links_job, deadline, "stage 1")

    link_rows = job_rows(links_job)
    log.info("stage 1 returned %d row(s)", len(link_rows))

    chosen, unmatched, ambiguous, superseded = pick_urls(link_rows, fixtures)
    log.info("%d match URL(s) line up with a fixture in the window; "
             "%d did not match any; %d ambiguous; %d superseded",
             len(chosen), len(unmatched), len(ambiguous), len(superseded))
    for url, cands in ambiguous:
        log.warning("   AMBIGUOUS %s -> %s", url[-40:], " | ".join(cands))
    for url, label, score, winner in superseded:
        log.warning("   SUPERSEDED %s claimed %s at %d, kept the %d match",
                    url[-40:], label, score, winner)
    for url, f in chosen:
        log.info("   %s v %s  ->  %s", f["home"][:20], f["away"][:20], url[-46:])
    for u in unmatched[:5]:
        log.info("   (skipped) %s", u[-56:])

    if not chosen:
        log.info("Nothing to scrape.")
        db.finish_run(run_id, fixtures=len(fixtures), stage1_job=str(links_job),
                      pages=0, written=0, unmatched=len(unmatched),
                      ambiguous=len(ambiguous), superseded=len(superseded),
                      status="idle", detail="no URL matched a fixture")
        return 0
    if args.dry_run:
        log.info("dry run: would scrape %d page(s) = %d credit(s)",
                 len(chosen), len(chosen))
        db.finish_run(run_id, fixtures=len(fixtures), stage1_job=str(links_job),
                      pages=len(chosen), unmatched=len(unmatched),
                      ambiguous=len(ambiguous), superseded=len(superseded),
                      status="dry-run")
        return 0

    # -- stage 2: the possession markets ---------------------------------
    if not args.matches_sitemap and not args.matches_job:
        raise SystemExit(
            "No match-detail sitemap id. Pass --matches-sitemap or set "
            "WS_SITEMAP_MATCHES in .env.")
    if args.matches_job:
        match_job = args.matches_job
        log.info("reusing stage-2 job %s", match_job)
    else:
        urls = [u for u, _ in chosen]
        match_job = start_job(args.matches_sitemap, start_urls=urls,
                              request_interval=args.interval,
                              custom_id="stage2-markets")
        log.info("stage 2 queued as job %s for %d page(s)", match_job, len(urls))
        db.note_run(run_id, stage2_job=str(match_job), pages=len(chosen))
        _wait(match_job, deadline, "stage 2")

    rows = job_rows(match_job)
    log.info("stage 2 returned %d row(s)", len(rows))

    # Stage 2 takes minutes, and the connection opened at the top has been
    # sitting idle inside a transaction the whole time. Neon closes those, so
    # without this the scrape completes, the credits are spent, and the import
    # dies on the first query.
    db.ensure_connection()

    import odds_sheet
    import import_odds as io_mod
    parsed = odds_sheet.parse_webscraper(rows)
    ready, problems = io_mod.resolve_rows(db, parsed)
    log.info("%d line(s) resolved, %d problem(s)", len(ready), len(problems))
    for r in ready:
        log.info("   ok  %s  over %s / under %s", r["_label"],
                 r["over_odds"], r["under_odds"])
    for p in problems:
        log.info("   --  %s", p)

    # Everything the run learned, recorded whichever way it ends. Kept in one
    # place so a preview and a write are described identically apart from the
    # count - the Scraper page should not have to guess which it is reading.
    # A page webscraper.io failed to load returns no rows at all - not the one
    # or two rows of a page without a market. On 17 Sep Brentford v Chelsea's
    # page failed that way, and counting it as an empty read would park a
    # fixture whose page was never actually seen.
    # ...and a page can also come back as a single blank row - no team names, no
    # market text - when it did not render. Brentford v Chelsea's page did that
    # on a retry the same morning. Only a row carrying something counts.
    returned = {(x.get("web_scraper_start_url") or x.get("web-scraper-start-url") or "")
                for x in rows
                if (x.get("teams") or "").strip() or (x.get("market_text") or "").strip()}
    failed = [f for u, f in chosen if u not in returned]
    for f in failed:
        log.warning("   page FAILED to load, not counted as a read: %s v %s",
                    f["home"], f["away"])
    notes = [str(p) for p in problems] + [
        f"page failed to load: {f['home']} v {f['away']}" for f in failed]
    tally = dict(fixtures=len(fixtures), stage1_job=str(links_job),
                 stage2_job=str(match_job), pages=len(chosen),
                 unmatched=len(unmatched), ambiguous=len(ambiguous),
                 superseded=len(superseded), rows_back=len(rows),
                 resolved=len(ready), problems=len(problems),
                 detail="; ".join(notes)[:2000] or None)

    if not args.write:
        log.info("preview only - pass --write to import")
        db.finish_run(run_id, written=0, status="preview",
                      credits=credits_left(), **tally)
        return 0

    for r in ready:
        r.pop("_label", None)
        r.pop("_flipped", None)
    written = db.upsert_lines(ready)
    log.info("Wrote %d line(s).", written)
    # Which of the pages we paid for actually carried a market. Recorded after
    # the write so a crash before this leaves the counts untouched rather than
    # parking a fixture on a run that never finished.
    found = {r["match_id"] for r in ready}
    if not args.matches_job:
        # A replay re-reads a scrape already counted when it ran; counting it
        # again would park fixtures on reads that never happened.
        db.record_attempts([f["match_id"] for u, f in chosen if u in returned],
                           found)
    unpark_round(db, found)
    db.finish_run(run_id, written=written, credits=credits_left(),
                  status="ok" if not problems else "ok-with-problems", **tally)
    return 0


if __name__ == "__main__":
    sys.exit(main())
