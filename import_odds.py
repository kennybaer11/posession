"""Import bookmaker possession lines from a small text file.

    python import_odds.py odds.txt            # load them
    python import_odds.py odds.txt --dry-run  # check the matching first

The scraper cannot fetch these - chance.cz serves odds from a client-side app
behind bot protection - so they are typed in. The format is deliberately close
to what you would write down while reading the site:

    # date       home            away        team     line  over  under
    2026-09-06   Arsenal         Chelsea     Arsenal  54.5   1.80  1.94
    2026-08-30   Chelsea         Brighton    Chelsea  47.5   1.85  1.88

Columns are whitespace-separated, so club names must not contain spaces -
write Man City, Nottingham or Brighton however you like and the matcher will
find them, since it compares against name, short name and abbreviation and
falls back to a fuzzy match. Lines starting with # are ignored.

Both prices matter. Implied probabilities on the two sides sum to more than 1,
and that excess is the bookmaker's margin; without the other side it cannot be
stripped out, and a model compared against a margin-inflated probability looks
better than it is. If you only have one, leave the other blank as "-".
"""

import argparse
import difflib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from db import Database  # noqa: E402


def _num(text):
    """Czech decimals use a comma: 1,94 -> 1.94, '54,5 a vice' -> 54.5."""
    if text is None:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(text))
    return float(m.group(0).replace(",", ".")) if m else None


def parse_chance(raw, n):
    """A row pasted straight from chance.cz's table.

    Tab-separated, in the site's own column order:

        Day  Match  Bet  Under  Under-odd  Over  Over-odd
        06.09.2026 <TAB> Arsenal - Chelsea <TAB> Procento drzeni mice Arsenal
        v zapasu <TAB> Mene nez 54,5 <TAB> 1,94 <TAB> 54,5 a vice <TAB> 1,75

    The club the line is about comes from the Bet column, not the Match column,
    because they are not always the same club - and when they disagree the Bet
    column is the one that says what you are actually betting on.
    """
    cells = [c.strip() for c in raw.split("\t") if c.strip()]
    if len(cells) < 5:
        return None

    day, match, bet = cells[0], cells[1], cells[2]
    rest = cells[3:]

    if " - " not in match and " – " not in match:
        return None
    sep = " - " if " - " in match else " – "
    home, away = (p.strip() for p in match.split(sep, 1))

    # "Procento drzeni mice ARSENAL v zapasu" - the club sits between the
    # phrase and the trailing "v zapasu".
    team = re.sub(r"(?i)^.*?(?:m[ií][cč]e|possession)\s+", "", bet)
    team = re.sub(r"(?i)\s+v\s+z[aá]pas.*$", "", team).strip() or home

    # Remaining cells are (under-text, under-odd, over-text, over-odd), but a
    # market may be offered one-sided, so read them by shape rather than index.
    nums = [_num(c) for c in rest]
    line = under = over = None
    if len(nums) >= 4:
        line, under, _, over = nums[0], nums[1], nums[2], nums[3]
    elif len(nums) >= 2:
        line, under = nums[0], nums[1]
    if line is None:
        return None

    date = day.strip()
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", date)
    if m:
        date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    return {"n": n, "date": date, "home": home.replace(" ", ""),
            "away": away.replace(" ", ""), "team": team.replace(" ", ""),
            "line": line, "over": over, "under": under}


def parse(path):
    """Read either format: the compact one, or a paste from chance.cz."""
    rows = []
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Route on what the row IS, not on whether it contains a tab.
        #
        # Two traps, both hit in practice. Keying off the tab alone rejected
        # good compact rows that happened to be tab-aligned, which is a natural
        # way to type them. Keying off " - " alone then broke compact rows
        # using a bare "-" for a missing price, since the surrounding spaces
        # look identical to a match separator.
        #
        # A chance.cz paste is both tab-separated AND has a cell holding two
        # club names either side of a dash. Requiring both is what separates
        # "Arsenal - Chelsea" from "53.5   -   U1.75".
        cells = [c.strip() for c in raw.split("\t")]
        looks_like_chance = "\t" in raw and any(
            re.search(r"[A-Za-z]{2,}.*\s[-–]\s.*[A-Za-z]{2,}", c) for c in cells)
        if looks_like_chance:
            row = parse_chance(raw, n)
            if row:
                rows.append(row)
            else:
                print(f"  line {n}: could not read as a chance.cz row: {raw[:70]!r}")
            continue

        parts = stripped.split("#", 1)[0].split()
        if len(parts) < 6:
            print(f"  line {n}: need at least 6 fields, got {len(parts)}: {raw!r}")
            continue
        date, home, away, team, value = parts[:5]

        # Prices may be tagged O1.75 / U1.94 in either order, which is the
        # recommended form: chance.cz lists UNDER first and this format
        # historically took OVER first, and a silent swap reverses which side
        # a bet is on. Tagging removes the ambiguity rather than trying to
        # detect it afterwards - which cannot be done reliably, since whether
        # OVER is the longer price depends on where the line sits relative to
        # that team's usual possession, not on the line alone.
        over = under = None
        untagged = []
        for tok in parts[5:7]:
            m = re.fullmatch(r"(?i)([ou])[:=]?(\d+(?:[.,]\d+)?)", tok)
            if m:
                if m.group(1).lower() == "o":
                    over = _num(m.group(2))
                else:
                    under = _num(m.group(2))
            else:
                untagged.append(tok)
        if untagged and over is None and under is None:
            over = untagged[0] if len(untagged) > 0 else "-"
            under = untagged[1] if len(untagged) > 1 else "-"
        rows.append({"n": n, "date": date, "home": home, "away": away,
                     "team": team, "line": _num(value),
                     "over": _num(over), "under": _num(under)})
    return rows


def team_lookup(db):
    """Every name we might reasonably be given, mapped to a team_id."""
    with db.conn.cursor() as cur:
        cur.execute("SELECT team_id, name, short_name, abbr FROM pl_teams")
        teams = cur.fetchall()
    index = {}
    for t in teams:
        for key in (t["name"], t["short_name"], t["abbr"]):
            if key:
                index[key.lower().replace(" ", "")] = t["team_id"]
    return index, {t["team_id"]: t["name"] for t in teams}


def resolve(name, index):
    key = name.lower().replace(" ", "")
    if key in index:
        return index[key]
    # Substring first - "Brighton" should find "Brighton and Hove Albion"
    hits = [v for k, v in index.items() if key in k or k in key]
    if len(set(hits)) == 1:
        return hits[0]
    close = difflib.get_close_matches(key, list(index), n=1, cutoff=0.75)
    return index[close[0]] if close else None


def find_match(db, date, team_a, team_b):
    """The match on that date between those two clubs, in EITHER order.

    Order-agnostic on purpose. A bookmaker's listing does not always put the
    home side first, and a hand-typed line is easy to write the other way
    round - but "Newcastle possession under 53.5" means the same thing whoever
    was at home. Insisting on the order would silently reject good data, so the
    pair is matched and the real venue is read back from the fixture.
    """
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT match_id, kickoff, home_team_id, away_team_id
            FROM pl_matches
            WHERE kickoff::date = %s::date
              AND ((home_team_id = %s AND away_team_id = %s)
                OR (home_team_id = %s AND away_team_id = %s))
        """, (date, team_a, team_b, team_b, team_a))
        row = cur.fetchone()
        if row:
            return row
        # Tolerate a kickoff that lands on the neighbouring day in another
        # timezone: a 21:00 kickoff can be written as either date.
        cur.execute("""
            SELECT match_id, kickoff, home_team_id, away_team_id
            FROM pl_matches
            WHERE ((home_team_id = %s AND away_team_id = %s)
                OR (home_team_id = %s AND away_team_id = %s))
              AND abs(EXTRACT(EPOCH FROM (kickoff - %s::timestamp))) < 129600
        """, (team_a, team_b, team_b, team_a, date))
        return cur.fetchone()


def main():
    ap = argparse.ArgumentParser(description="Import possession lines.")
    ap.add_argument("path")
    ap.add_argument("--bookmaker", default="chance.cz")
    ap.add_argument("--closing", action="store_true",
                    help="mark these as closing lines")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = Database()
    db.ensure_schema(with_views=False)
    index, names = team_lookup(db)

    if not Path(args.path).exists():
        print(f"{args.path} does not exist - nothing to import.")
        return 0

    parsed = parse(args.path)
    if not parsed:
        # An empty odds file is the normal state between weekends, not an
        # error. Failing here would turn every quiet run red, the same trap
        # the scraper itself fell into.
        print("No lines in the file - nothing to import.")
        return 0

    ready, problems, warnings = [], [], []
    for r in parsed:
        home_id = resolve(r["home"], index)
        away_id = resolve(r["away"], index)
        team_id = resolve(r["team"], index)
        if not (home_id and away_id and team_id):
            missing = [lbl for lbl, v in (("home", home_id), ("away", away_id),
                                          ("team", team_id)) if not v]
            problems.append(f"line {r['n']}: unknown club for {', '.join(missing)} "
                            f"({r['home']} / {r['away']} / {r['team']})")
            continue
        match = find_match(db, r["date"], home_id, away_id)
        if not match:
            problems.append(f"line {r['n']}: no {r['home']} v {r['away']} "
                            f"on {r['date']}")
            continue
        if team_id not in (match["home_team_id"], match["away_team_id"]):
            problems.append(f"line {r['n']}: {r['team']} did not play in that match")
            continue

        ready.append({
            "match_id": match["match_id"], "team_id": team_id,
            "line": float(r["line"]),
            "over_odds": r["over"], "under_odds": r["under"],
            "bookmaker": args.bookmaker,
            "is_closing": 1 if args.closing else 0,
            "captured_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "note": None,
            "_label": f"{names[match['home_team_id']]} v "
                      f"{names[match['away_team_id']]} "
                      f"({match['kickoff']:%d %b %Y}) - {names[team_id]} "
                      f"{'HOME' if team_id == match['home_team_id'] else 'away'} "
                      f"{r['line']}",
            "_flipped": home_id != match["home_team_id"],
        })

    print(f"Parsed {len(parsed)} line(s): {len(ready)} matched, "
          f"{len(problems)} problem(s).\n")
    for r in ready:
        both = "both prices" if r["over_odds"] and r["under_odds"] else "one price"
        flip = "  [teams were listed the other way round]" if r["_flipped"] else ""
        print(f"  ok   {r['_label']}  over {r['over_odds']} / "
              f"under {r['under_odds']}  [{both}]{flip}")
    for p in problems:
        print(f"  --   {p}")
    for w in warnings:
        print(f"  !!   {w}")

    if args.dry_run:
        print("\n--- dry run: nothing written ---")
        return 0
    if not ready:
        return 0 if not problems else 1

    for r in ready:
        r.pop("_label"); r.pop("_flipped")
    n = db.upsert_lines(ready)
    print(f"\nWrote {n} line(s) to pl_possession_line.")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
