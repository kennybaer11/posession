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


def upcoming_fixtures(db, hours, skip_priced=False):
    """Fixtures kicking off within the window, from OUR data.

    skip_priced drops the ones we already hold a line for, which is what makes
    a repeat run nearly free: one match page is one credit, so re-scraping a
    fixture whose odds are already recorded spends money to learn nothing.
    Fixtures the bookmaker does not price are deliberately still included -
    they carry no line, and a market can appear closer to kickoff.
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
            ORDER BY m.kickoff
        """, (hours, skip_priced))
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
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    from db import Database
    db = Database()
    db.ensure_schema(with_views=False)

    fixtures = upcoming_fixtures(db, args.hours, args.skip_priced)
    log.info("%d fixture(s) kicking off in the next %dh%s", len(fixtures),
             args.hours, " without odds" if args.skip_priced else "")
    for f in fixtures[:12]:
        log.info("   %s  %s v %s  [%s]", f["kickoff"].strftime("%d %b %H:%M"),
                 f["home"][:22], f["away"][:22], f["competition"])
    if not fixtures:
        log.info("Nothing due - stopping before spending any credits.")
        return 0

    # -- stage 1: which match pages exist --------------------------------
    if args.links_job:
        links_job = args.links_job
        log.info("reusing stage-1 job %s", links_job)
    elif args.dry_run:
        log.info("dry run: would start stage-1 job on sitemap %s", LINKS_SITEMAP)
        db.close()
        return 0
    else:
        links_job = start_job(LINKS_SITEMAP, request_interval=args.interval,
                              custom_id="stage1-links")
        log.info("stage 1 queued as job %s", links_job)
        wait_for(links_job)

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
        db.close()
        return 0
    if args.dry_run:
        log.info("dry run: would scrape %d page(s) = %d credit(s)",
                 len(chosen), len(chosen))
        db.close()
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
        wait_for(match_job)

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

    if not args.write:
        log.info("preview only - pass --write to import")
        db.close()
        return 0

    for r in ready:
        r.pop("_label", None)
        r.pop("_flipped", None)
    log.info("Wrote %d line(s).", db.upsert_lines(ready))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
