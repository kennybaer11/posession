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


def share_one_connection():
    """Render every page over a single database connection.

    app.db() opens one connection per request and closes it on teardown, which
    is right for a web server and wrong here: a full build is ~140 pages, and
    140 fresh TLS handshakes to a US-East database from Europe costs more than
    all the queries put together. The pages are read-only, so one connection
    for the whole build is safe.
    """
    conn = webapp.psycopg.connect(webapp.os.environ["DATABASE_URL"],
                                  row_factory=webapp.dict_row)
    webapp.db = lambda: conn
    return conn


def targets():
    """(url, output path) for every page, discovered from the database."""
    pages = [
        ("/", "index.html"),
        ("/teams", "teams.html"),
        ("/matches", "matches.html"),
        ("/fixtures", "fixtures.html"),
        ("/model", "model.html"),
        ("/bets", "bets.html"),
    ]
    with webapp.app.app_context():
        for r in webapp.query("SELECT DISTINCT season FROM pl_matches ORDER BY season"):
            pages.append((f"/matches?season={r['season']}",
                          f"matches-{r['season']}.html"))
        for r in webapp.query("SELECT team_id FROM pl_teams ORDER BY team_id"):
            pages.append((f"/team/{r['team_id']}", f"team/{r['team_id']}.html"))
        for r in webapp.query("SELECT DISTINCT match_id FROM pl_team_match"):
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
        if url == "/":
            return "index.html"
        m = re.fullmatch(r"/matches\?season=([^&\"]+)", url)
        if m:
            return f"matches-{m.group(1)}.html"
        m = re.fullmatch(r"/(team|match)/([^/?\"]+)", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}.html"
        if url.startswith("/static/"):
            return url[1:]
        return url.lstrip("/") + ".html"

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
    client = webapp.app.test_client()
    pages = targets()
    written = failed = 0

    for url, rel in pages:
        resp = client.get(url)
        if resp.status_code != 200:
            print(f"  FAILED {resp.status_code}  {url}")
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
