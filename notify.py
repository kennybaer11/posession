"""Telegram alerts when new possession odds are recorded.

    python notify.py             send alerts for lines not yet announced
    python notify.py --dry-run   print the message, send and mark nothing
    python notify.py --whoami    list the chats that have messaged the bot
    python notify.py --test      send a one-line test message

Runs in both workflows after the advice is frozen, so a message carries the
same advice the site publishes in that run. A line is marked as announced only
once Telegram confirms delivery: a failed send leaves it unmarked, and the next
run tries again rather than losing it.

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Without them it logs and exits
cleanly, so the workflow step is harmless until the bot is set up.
"""

import argparse
import html
import logging
import os
import sys
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("notify")

PRAGUE = ZoneInfo("Europe/Prague")
SITE = os.getenv("SITE_URL", "https://kennybaer11.github.io/posession/")
LEAGUE_NAMES = {"PL": "Premier League", "LaLiga": "LaLiga", "BL1": "Bundesliga"}
TELEGRAM_LIMIT = 4000       # the API allows 4096; leave room for the footer


def api(method, token, **params):
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                      data=params, timeout=30)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not body.get("ok"):
        # Never log the URL: it contains the bot token.
        raise RuntimeError(f"Telegram {method} failed: {body.get('description') or r.status_code}")
    return body["result"]


def new_lines(db):
    """Lines not yet announced whose match is still to be played."""
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT l.match_id, l.team_id, l.line, l.bookmaker,
                   l.over_odds, l.under_odds, l.captured_at,
                   m.kickoff, m.competition,
                   t.name AS team, ht.name AS home, at_.name AS away,
                   first.line AS recorded_line,
                   a.side, a.edge, a.rating, a.backed, a.fallback, a.pred,
                   a.line AS advice_line
            FROM pl_possession_line l
            JOIN pl_matches m ON m.match_id = l.match_id
            JOIN pl_teams t   ON t.team_id = l.team_id
            JOIN pl_teams ht  ON ht.team_id = m.home_team_id
            JOIN pl_teams at_ ON at_.team_id = m.away_team_id
            -- the line the record counts for this match: the first captured
            LEFT JOIN LATERAL (
                SELECT f.line FROM pl_possession_line f
                WHERE f.match_id = l.match_id AND f.bookmaker = l.bookmaker
                ORDER BY f.captured_at ASC NULLS LAST, f.line
                LIMIT 1) first ON TRUE
            LEFT JOIN pl_advice a ON a.match_id = l.match_id
                                 AND a.bookmaker = l.bookmaker
            WHERE l.notified_at IS NULL
              AND m.kickoff > (now() AT TIME ZONE 'UTC')
              AND (a.match_id IS NOT NULL
                   OR l.captured_at < (now() AT TIME ZONE 'UTC') - INTERVAL '2 hours')
            ORDER BY m.kickoff, m.match_id, l.captured_at
        """)
        return cur.fetchall()


def describe(r):
    ko = r["kickoff"].replace(tzinfo=ZoneInfo("UTC")).astimezone(PRAGUE)
    e = html.escape
    line = float(r["line"])
    prices = " / ".join(filter(None, (
        f"Over {float(r['over_odds']):.2f}" if r["over_odds"] else None,
        f"Under {float(r['under_odds']):.2f}" if r["under_odds"] else None)))
    out = [
        f"<b>{e(r['home'])} v {e(r['away'])}</b>",
        f"{LEAGUE_NAMES.get(r['competition'], e(r['competition']))} · "
        f"{ko:%a %d %b %H:%M}",
        f"{e(r['team'])} possession <b>{line:.1f}</b> · {prices}",
    ]
    moved = (r["recorded_line"] is not None
             and float(r["recorded_line"]) != line)
    if moved:
        out.append(f"<i>Line moved - the record keeps the opening "
                   f"{float(r['recorded_line']):.1f}</i>")
    if r["side"] is not None or r["backed"] is not None:
        if r["backed"]:
            advice = (f"Model {float(r['pred']):.1f} → <b>{r['side']}</b> · "
                      f"edge {float(r['edge']):+.1%} · stake {r['rating']}/10")
        else:
            advice = f"Model {float(r['pred']):.1f} → no bet"
        if r["fallback"]:
            advice += " · <i>naive fallback</i>"
        if moved:
            advice += f" (on {float(r['advice_line']):.1f})"
        out.append(advice)
    else:
        out.append("<i>No advice recorded yet</i>")
    return "\n".join(out)


# A stake change this size is worth a message on its own; anything smaller is
# the model breathing, and saying so every few hours would be noise.
RATING_STEP = 2


def changed_advice(db):
    """Tips whose advice has moved since Telegram was told about them.

    The advice is recomputed on every run until kickoff, so the announcement
    is only a snapshot: Forest v Arsenal was announced as "no bet" and became
    OVER a day later, when the 1X2 odds for the match were published. Reported
    when the bet appears or disappears, when the side flips, or when the stake
    moves by RATING_STEP or more.
    """
    with db.conn.cursor() as cur:
        cur.execute(f"""
            SELECT a.match_id, a.bookmaker, a.kickoff, a.competition, a.line,
                   a.side, a.odds, a.edge, a.rating, a.pred, a.backed,
                   a.told_side, a.told_rating,
                   t.name AS team, ht.name AS home, at_.name AS away
            FROM pl_advice a
            JOIN pl_matches m ON m.match_id = a.match_id
            JOIN pl_teams t   ON t.team_id = a.team_id
            JOIN pl_teams ht  ON ht.team_id = m.home_team_id
            JOIN pl_teams at_ ON at_.team_id = m.away_team_id
            WHERE a.told_at IS NOT NULL
              AND a.kickoff > (now() AT TIME ZONE 'UTC')
              AND m.kickoff = a.kickoff          -- not a postponed fixture
              AND (a.side IS DISTINCT FROM a.told_side
                   OR abs(COALESCE(a.rating, 0) - COALESCE(a.told_rating, 0)) >= {RATING_STEP})
            ORDER BY a.kickoff, a.match_id
        """)
        return cur.fetchall()


def describe_change(r):
    ko = r["kickoff"].replace(tzinfo=ZoneInfo("UTC")).astimezone(PRAGUE)
    e = html.escape

    def advice(side, rating):
        if not side:
            return "no bet"
        out = f"<b>{side}</b> {float(r['line']):.1f}"
        if r["odds"]:
            out += f" @ {float(r['odds']):.2f}"
        if rating:
            out += f" · stake {rating}/10"
        return out

    return "\n".join([
        f"<b>{e(r['home'])} v {e(r['away'])}</b>",
        f"{LEAGUE_NAMES.get(r['competition'], e(r['competition']))} · "
        f"{ko:%a %d %b %H:%M} · {e(r['team'])}",
        f"{advice(r['told_side'], r['told_rating'])} → "
        f"{advice(r['side'], r['rating'])}"
        + (f" · edge {float(r['edge']):+.1%}" if r["backed"] and r["edge"] is not None else ""),
    ])


def build_change_messages(rows):
    header = (f"🔄 <b>Advice changed</b> - {len(rows)} tip"
              f"{'' if len(rows) == 1 else 's'}")
    footer = ("\n\n<i>The advice is recomputed until kickoff; what the record keeps "
              "is the last version before it.</i>")
    messages, current = [], header
    for r in rows:
        block = "\n\n" + describe_change(r)
        if len(current) + len(block) + len(footer) > TELEGRAM_LIMIT:
            messages.append(current + footer)
            current = header + " (cont.)"
        current += block
    messages.append(current + footer)
    return messages


def mark_told(db, rows):
    """Remember the advice just reported, so it is reported once."""
    with db.conn.cursor() as cur:
        for r in rows:
            cur.execute("""UPDATE pl_advice
                              SET told_side = side, told_rating = rating, told_at = NOW()
                            WHERE match_id = %s AND bookmaker = %s""",
                        (r["match_id"], r["bookmaker"]))
    db.conn.commit()


def build_messages(rows):
    header = (f"🟢 <b>New possession odds</b> - {len(rows)} line"
              f"{'' if len(rows) == 1 else 's'}")
    footer = (f"\n\n<i>Stakes stay capped until the advice record is long enough "
              f"to mean something.</i>\n<a href=\"{SITE}all-fixtures.html\">Fixtures</a>")
    messages, current = [], header
    for r in rows:
        block = "\n\n" + describe(r)
        if len(current) + len(block) + len(footer) > TELEGRAM_LIMIT:
            messages.append(current + footer)
            current = header + " (cont.)"
        current += block
    messages.append(current + footer)
    return messages


def main():
    ap = argparse.ArgumentParser(description="Telegram alerts for new odds.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--whoami", action="store_true")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")

    if args.whoami:
        if not token:
            raise SystemExit("Set TELEGRAM_BOT_TOKEN first.")
        seen = {}
        for u in api("getUpdates", token):
            c = (u.get("message") or u.get("channel_post") or {}).get("chat") or {}
            if c.get("id"):
                seen[c["id"]] = c.get("title") or " ".join(
                    filter(None, (c.get("first_name"), c.get("last_name"))))
        if not seen:
            print("No chats yet - send your bot any message in Telegram, then run this again.")
        for cid, name in seen.items():
            print(f"TELEGRAM_CHAT_ID={cid}    ({name})")
        return 0

    if args.test:
        if not (token and chat):
            raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first.")
        api("sendMessage", token, chat_id=chat,
            text="✅ Possession odds alerts are connected.")
        print("Test message sent.")
        return 0

    from db import Database
    db = Database()
    db.ensure_schema(with_views=False)
    rows = new_lines(db)
    changed = changed_advice(db)
    if not rows and not changed:
        log.info("No new lines to announce, no advice changed.")
        db.close()
        return 0

    messages = build_messages(rows) if rows else []
    messages += build_change_messages(changed) if changed else []
    if args.dry_run or not (token and chat):
        if not args.dry_run:
            log.info("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - "
                     "%d line(s) and %d change(s) left unannounced.",
                     len(rows), len(changed))
        for msg in messages:
            print(msg, end="\n\n")
        db.close()
        return 0

    for msg in messages:
        api("sendMessage", token, chat_id=chat, text=msg, parse_mode="HTML",
            disable_web_page_preview="true")
    # Marked only after every message went through.
    with db.conn.cursor() as cur:
        for r in rows:
            cur.execute("""UPDATE pl_possession_line SET notified_at = NOW()
                           WHERE match_id=%s AND team_id=%s AND line=%s
                             AND bookmaker=%s""",
                        (r["match_id"], r["team_id"], r["line"], r["bookmaker"]))
    db.conn.commit()
    # Both kinds of message leave the same mark: what Telegram now knows.
    mark_told(db, rows + changed)
    log.info("Announced %d line(s) and %d change(s) in %d message(s).",
             len(rows), len(changed), len(messages))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
