"""Render the web UI to a folder of static HTML.

    python export_static.py [outdir]      # default: site/

Why this exists: the data only changes when the scraper runs, and every page is
read-only, so there is nothing a live server does here that a snapshot cannot.
This lets GitHub Pages host the UI for free and always-on, with the database
credentials staying inside the GitHub Action that builds it - a deployed Flask
app would need DATABASE_URL sitting on a third-party host instead.

Pages are rendered THROUGH the Flask app's own test client rather than
re-implemented, so the static build and `python app.py` can never drift apart.
"""

import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import app as webapp  # noqa: E402  (must follow load_dotenv)


_conn = None


def share_one_connection():
    """Render every page over a single database connection.

    app.db() opens one connection per request and closes it on teardown, which
    is right for a web server and wrong here: a full build is ~540 pages, and
    540 fresh TLS handshakes to a US-East database from Europe costs more than
    all the queries put together. The pages are read-only, so one connection
    for the whole build is safe.

    Safe, but not immortal: one connection held across a build that takes
    minutes is exactly what Neon's pooler drops. Calling this again replaces a
    dead handle, which is what render() does rather than let one drop cascade.
    """
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = webapp.psycopg.connect(webapp.os.environ["DATABASE_URL"],
                                   row_factory=webapp.dict_row)
    webapp.db = lambda: _conn
    return _conn


def render(client, url):
    """Fetch one page, reconnecting once if the connection died under us.

    Without this, a single dropped connection does not fail one page - it
    fails every page after it, because they all share the handle. A build that
    reached the slowest page and then reported 525 failures was one dead
    socket, not 525 broken pages.
    """
    try:
        resp = client.get(url)
        if resp.status_code == 200:
            return resp, None
        reason = f"HTTP {resp.status_code}"
    except Exception as exc:                     # noqa: BLE001 - reported below
        reason = f"{type(exc).__name__}: {exc}"

    print(f"  reconnecting after {reason}  ({url})")
    share_one_connection()
    try:
        resp = client.get(url)
        return resp, (None if resp.status_code == 200
                      else f"{reason}, then HTTP {resp.status_code}")
    except Exception as exc:                     # noqa: BLE001
        return None, f"{reason}, then {type(exc).__name__}: {exc}"


def targets():
    """(url, output path) for every page, discovered from the database."""
    # The Premier League keeps the bare filenames so existing links still work;
    # the other leagues get a prefixed copy of each page.
    pages = []
    for code, _ in webapp.LEAGUES:
        pre = "" if code == "PL" else f"{code.lower()}-"
        q = "" if code == "PL" else f"?league={code}"
        pages += [
            (f"/{q}", f"{pre}index.html"),
            (f"/teams{q}", f"{pre}teams.html"),
            (f"/matches{q}", f"{pre}matches.html"),
            (f"/fixtures{q}", f"{pre}fixtures.html"),
            (f"/model{q}", f"{pre}model.html"),
            (f"/bets{q}", f"{pre}bets.html"),
        ]
    with webapp.app.app_context():
        for r in webapp.query("SELECT DISTINCT competition, season FROM pl_matches "
                              "ORDER BY competition, season"):
            code, season = r["competition"], r["season"]
            pre = "" if code == "PL" else f"{code.lower()}-"
            q = f"?season={season}" + ("" if code == "PL" else f"&league={code}")
            pages.append((f"/matches{q}", f"{pre}matches-{season}.html"))
        for r in webapp.query("SELECT team_id FROM pl_teams ORDER BY team_id"):
            pages.append((f"/team/{r['team_id']}", f"team/{r['team_id']}.html"))
        # Played matches have a detail page. Upcoming ones with a recorded
        # betting line need one too: the Bets page links every row, and a link
        # to a page that was never rendered is a 404 on a site where every
        # page returned 200 when it was built.
        for r in webapp.query("""
                SELECT DISTINCT match_id FROM pl_team_match
                UNION
                SELECT DISTINCT match_id FROM pl_possession_line"""):
            pages.append((f"/match/{r['match_id']}", f"match/{r['match_id']}.html"))
    return pages


def rewrite_links(html, depth):
    """Turn the app's absolute URLs into relative paths that work anywhere.

    GitHub Pages serves a project site from /<repo>/, so a link to "/teams"
    would resolve against the domain root and 404. Relative paths work under a
    subpath, at a domain root, and from a local file:// open alike.
    """
    up = "../" * depth

    def to_static(url):
        """Map an app URL to the file targets() wrote it to.

        The two must agree exactly: a mismatch produces links that 404 on a
        site where every page returned 200 when it was rendered.
        """
        if url.startswith("/static/"):
            return url[1:]

        m = re.fullmatch(r"/(team|match)/([^/?\"]+)", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}.html"

        path, _, qs = url.partition("?")
        params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        # The Premier League keeps bare filenames; the others are prefixed.
        code = params.get("league", "PL")
        prefix = "" if code == "PL" else f"{code.lower()}-"

        name = path.strip("/") or "index"
        season = params.get("season")
        if name == "matches" and season:
            name = f"matches-{season}"
        return f"{prefix}{name}.html"

    def repl(match):
        attr, url = match.group(1), match.group(2)
        if url.startswith(("http://", "https://", "#", "mailto:")):
            return match.group(0)
        return f'{attr}="{up}{to_static(url)}"'

    return re.sub(r'(href|src)="(/[^"]*)"', repl, html)


def main(outdir="site"):
    out = BASE_DIR / outdir
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    share_one_connection()
    # A build should say why a page broke, not swallow it into a 500.
    webapp.app.config["PROPAGATE_EXCEPTIONS"] = True
    client = webapp.app.test_client()
    pages = targets()
    written = failed = 0

    for url, rel in pages:
        resp, reason = render(client, url)
        if reason is not None:
            print(f"  FAILED {url}  {reason}")
            failed += 1
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        depth = len(Path(rel).parts) - 1
        dest.write_text(rewrite_links(resp.get_data(as_text=True), depth),
                        encoding="utf-8")
        written += 1

    shutil.copytree(BASE_DIR / "static", out / "static")
    # Stops GitHub Pages running the output through Jekyll, which would drop
    # any file or folder whose name begins with an underscore.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Wrote {written} page(s) to {out}"
          + (f" - {failed} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "site"))
