"""Health checks for the odds scraper, reported on Telegram.

    python monitor.py            check, and send any alert that is due
    python monitor.py --dry-run  print what would be sent, send and record nothing

Runs at the end of every data workflow run. notify.py says when odds ARRIVE;
this says when something is stopping them from arriving, which on 16 Sep went
unnoticed twice in one day:

  - Atletico v Osasuna's market was scraped and thrown away by a name bug. The
    run said so in its detail column, and nobody looks at that column.
  - For three and a half hours no scheduled run looked at the bookmaker at all,
    and Levante v Athletic's market opened in that window unseen.

Each alert has a key and a cooldown in pl_alert, so a problem that lasts all
afternoon is reported once, not every hour. An alert is recorded only after
Telegram accepts it.
"""

import argparse
import html
import logging
import os
import sys
from zoneinfo import ZoneInfo

log = logging.getLogger("monitor")

PRAGUE = ZoneInfo("Europe/Prague")

# A fixture kicking off within KICKOFF_HOURS with no odds, that no run has read
# for STALE_HOURS, is overdue: a market opening now would be missed.
KICKOFF_HOURS = 6
STALE_HOURS = 3

# No real odds scrape - one that ran, not skipped or replayed - for this long
# means the schedule, the cron trigger or the token has stopped working.
SILENT_HOURS = 5

# A 'running' row older than this is a process that died without reporting.
STUCK_MINUTES = 60

LOW_CREDITS = 100


def local(ts):
    if ts is None:
        return "never"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    return ts.astimezone(PRAGUE).strftime("%a %d %b %H:%M")


def due(cur, key, cooldown_hours):
    cur.execute("""SELECT 1 FROM pl_alert WHERE alert_key = %s
                   AND sent_at > now() - (%s * INTERVAL '1 hour')""",
                (key, cooldown_hours))
    return cur.fetchone() is None


def checks(db):
    """Every alert currently due, as (key, message, mark) triples.

    mark is what to record once the message is delivered: ("alert", key) for a
    cooldown alert, ("run", run_id) for a one-off about a specific run.
    """
    e = html.escape
    out = []
    with db.conn.cursor() as cur:
        # 1. A run rejected lines it had scraped - data lost unless someone acts.
        cur.execute("""SELECT run_id, started_at, source, problems, detail
                       FROM pl_scrape_run
                       WHERE problems > 0 AND alerted_at IS NULL
                         AND started_at > now() - INTERVAL '2 days'
                       ORDER BY started_at""")
        for r in cur.fetchall():
            out.append((None,
                        f"⚠️ <b>Scraped odds were rejected</b> - run {local(r['started_at'])} "
                        f"({r['source']}), {r['problems']} line(s):\n"
                        f"<code>{e((r['detail'] or '')[:600])}</code>\n"
                        f"The market was found but could not be matched, so it was not "
                        f"recorded. This usually needs a code fix.",
                        ("run", r["run_id"])))

        # 2. A run crashed, or died without reporting.
        cur.execute(f"""SELECT run_id, started_at, source, status, detail
                        FROM pl_scrape_run
                        WHERE alerted_at IS NULL
                          AND started_at > now() - INTERVAL '2 days'
                          AND NOT recovered
                          AND (status = 'error'
                               OR (status = 'timeout'
                                   AND started_at < now() - INTERVAL '90 minutes')
                               OR (status = 'running'
                                   AND started_at < now() - INTERVAL '{STUCK_MINUTES} minutes'))
                        ORDER BY started_at""")
        for r in cur.fetchall():
            what = ("crashed" if r["status"] == "error"
                    else "timed out and has not been recovered after 90 min"
                    if r["status"] == "timeout"
                    else f"has been running over {STUCK_MINUTES} min - probably died")
            last_line = (r["detail"] or "").strip().splitlines()[-1:] or [""]
            out.append((None,
                        f"🛑 <b>Odds run {what}</b> - started {local(r['started_at'])} "
                        f"({r['source']})\n<code>{e(last_line[0][:300])}</code>",
                        ("run", r["run_id"])))

        # 3. Nobody has looked at the bookmaker for too long.
        cur.execute("""SELECT max(started_at) AS last FROM pl_scrape_run
                       WHERE NOT reused_jobs
                         AND status IN ('ok', 'ok-with-problems', 'idle')""")
        last = cur.fetchone()["last"]
        cur.execute(f"""SELECT count(*) AS n FROM pl_scrape_run
                        WHERE NOT reused_jobs
                          AND status IN ('ok', 'ok-with-problems', 'idle')
                          AND started_at > now() - INTERVAL '{SILENT_HOURS} hours'""")
        if cur.fetchone()["n"] == 0 and due(cur, "silent", SILENT_HOURS):
            out.append(("silent",
                        f"🔇 <b>No odds scrape for over {SILENT_HOURS} hours</b> - last real "
                        f"run {local(last)}. Check the cron-job.org trigger, the GitHub "
                        f"Actions runs and the WEBSCRAPER_TOKEN secret.",
                        ("alert", "silent")))

        # 4. A match close to kickoff, without odds, not read recently.
        cur.execute(f"""
            SELECT m.match_id, m.kickoff, m.competition, ht.name AS home,
                   at_.name AS away, a.last_attempt, a.attempts
            FROM pl_matches m
            JOIN pl_teams ht  ON ht.team_id = m.home_team_id
            JOIN pl_teams at_ ON at_.team_id = m.away_team_id
            LEFT JOIN pl_odds_attempt a ON a.match_id = m.match_id
            WHERE m.kickoff BETWEEN (now() AT TIME ZONE 'UTC')
                  AND (now() AT TIME ZONE 'UTC') + INTERVAL '{KICKOFF_HOURS} hours'
              AND NOT EXISTS (SELECT 1 FROM pl_possession_line l
                              WHERE l.match_id = m.match_id)
              AND (a.last_attempt IS NULL
                   OR a.last_attempt < now() - INTERVAL '{STALE_HOURS} hours')
            ORDER BY m.kickoff""")
        overdue = [r for r in cur.fetchall()
                   if due(cur, f"overdue:{r['match_id']}", STALE_HOURS)]
        if overdue:
            lines = "\n".join(
                f"• {e(r['home'])} v {e(r['away'])} - kickoff {local(r['kickoff'])}, "
                f"last read {local(r['last_attempt'])}" for r in overdue)
            out.append((None,
                        f"⏰ <b>{len(overdue)} match(es) near kickoff not checked for "
                        f"{STALE_HOURS}h+</b>\n{lines}\nA market opening now would be missed.",
                        ("alerts", [f"overdue:{r['match_id']}" for r in overdue])))

        # 5. Credits.
        cur.execute("""SELECT credits FROM pl_scrape_run WHERE credits IS NOT NULL
                       ORDER BY started_at DESC LIMIT 1""")
        row = cur.fetchone()
        if row and row["credits"] < LOW_CREDITS and due(cur, "credits", 24):
            out.append(("credits",
                        f"🪫 <b>webscraper.io credits low: {row['credits']}</b> - top up "
                        f"before scraping stops.",
                        ("alert", "credits")))
    return out


def mark(db, how, message):
    kind, target = how
    with db.conn.cursor() as cur:
        if kind == "run":
            cur.execute("UPDATE pl_scrape_run SET alerted_at = NOW() WHERE run_id = %s",
                        (target,))
        else:
            for key in ([target] if kind == "alert" else target):
                cur.execute("""INSERT INTO pl_alert (alert_key, sent_at, message)
                               VALUES (%s, NOW(), %s)
                               ON CONFLICT (alert_key) DO UPDATE
                               SET sent_at = NOW(), message = EXCLUDED.message""",
                            (key, message[:1000]))
    db.conn.commit()


def main():
    ap = argparse.ArgumentParser(description="Scraper health alerts.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    from dotenv import load_dotenv
    load_dotenv()
    from db import Database
    from notify import api

    db = Database()
    db.ensure_schema(with_views=False)
    alerts = checks(db)
    if not alerts:
        log.info("All healthy - nothing to report.")
        db.close()
        return 0

    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    for _, message, how in alerts:
        if args.dry_run or not (token and chat):
            print(message, end="\n\n")
            continue
        api("sendMessage", token, chat_id=chat, text=message, parse_mode="HTML",
            disable_web_page_preview="true")
        mark(db, how, message)
    log.info("%d alert(s) %s.", len(alerts),
             "would be sent" if args.dry_run or not (token and chat) else "sent")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
