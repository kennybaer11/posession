# Premier League stats → Postgres, structured for prediction models

Pulls match stats from premierleague.com's own JSON API into PostgreSQL,
shaped so you can train an H2H prediction model without leaking future
information into your features.

The whole thing runs unattended on GitHub Actions and writes to a free Neon
Postgres database that you can query from pandas anywhere.

## Why Postgres instead of the Wedos MariaDB

Nothing was wrong with MariaDB — the blocker was that Wedos refuses external
connections, so the data was unreachable from Python. That's fatal for
modelling: you'd be exporting CSVs by hand before every retrain.

Neon accepts normal connections, which removes three moving parts at once: no
PHP sync script, no Wedos cron, no `.sql` import step. Python writes directly.

## One-time setup

**1. Create the database.** Sign up at [neon.tech](https://neon.tech) (free
tier is far more than this needs — the whole dataset is under 1 MB). Create a
project, then copy the connection string from the dashboard. It looks like:

```
postgresql://user:PASSWORD@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
```

**2. Point the scraper at it.** Copy `.env.example` to `.env` and paste that
string as `DATABASE_URL`.

**3. Load the data.**

```bash
pip install -r requirements.txt
python main.py
```

That creates every table and view and fills them. Takes a couple of minutes.

**4. Automate it.** Push this folder to a GitHub repo, then add the connection
string under *Settings → Secrets and variables → Actions* as `DATABASE_URL`.
`.github/workflows/scrape.yml` then runs hourly on GitHub's machines — nothing
on your PC, nothing on Wedos.

## Using it from Python

This is the payoff. `load.py` wraps it:

```python
from load import training_set, fixtures, feature_columns, time_split

train    = training_set(min_history=3)   # played matches + real outcome
upcoming = fixtures()                    # next fixtures, same feature names
feats    = feature_columns(train, upcoming)
tr, holdout = time_split(train)          # split by DATE, never at random
```

Two sharp edges it handles for you:

- **`postgresql://` maps to psycopg2 in SQLAlchemy**, which isn't installed
  (we use psycopg 3). Neon hands you exactly that URL form, so passing it
  straight to `create_engine` fails with a confusing import error. `load.py`
  rewrites the scheme.
- **`feature_columns` returns only columns present in *both* sets.** A feature
  that exists only in training can't be used to predict — better to exclude it
  up front than to discover it at scoring time.

Split by date, never randomly. A random split lets the model learn from matches
played *after* the ones it's scored on — the same leak the form windows are
built to avoid, reintroduced at the last step.

## The schema

| Table | Contents |
| --- | --- |
| `pl_teams` | One row per club |
| `pl_matches` | One row per match, **played and scheduled** |
| `pl_team_appearance` | Every fixture in **any** competition — the rest-day calendar |
| `pl_team_match` | One row per team per match — 36 stats plus key opponent figures |

| View | Purpose |
| --- | --- |
| `v_match_features` | **Training set** — form before kickoff + actual result |
| `v_fixture_features` | **Prediction set** — upcoming fixtures, same feature names |
| `v_team_form` | Point-in-time rolling form (5/10 match and same-venue windows) |
| `v_team_form_current` | Each team's form as of now |
| `v_team_rest` | Rest days and congestion, all competitions |
| `v_team_match` | A team's row with the opponent's full stat line (for/against) |
| `v_h2h` | Head-to-head record per club pair |
| `v_latest_team_stats` | Each team's most recent match |

### Why the two feature views are separate

The part that's easiest to get wrong.

**Training rows may only use what was known before kickoff.** Every window in
`v_team_form` is `ROWS BETWEEN n PRECEDING AND 1 PRECEDING`. That trailing
`AND 1 PRECEDING` excludes the current match. Without it, a match's own result
becomes one of its own features — such a model backtests beautifully and fails
on real fixtures.

**Upcoming fixtures have no row to attach a window to**, so they can't use that
view at all; every feature would be NULL. `v_fixture_features` uses
`v_team_form_current`, whose windows legitimately *include* the latest match,
because relative to an unplayed fixture every completed match is in the past.

### Rest days need every competition

Rest computed from league games alone is badly wrong:

| Match | League-only | True rest | Came from |
| --- | --- | --- | --- |
| Arsenal, 21 Aug | 89 days | **5 days** | Community Shield |
| Arsenal, 11 Apr | 28 days | **4 days** | Champions League |
| Man City, 23 Aug | 91 days | **7 days** | Community Shield |

The same API serves the Champions League, Europa League, Conference League, FA
Cup, EFL Cup and Community Shield, and — verified — uses **the same team ids**
across all of them, so no second source is needed. `v_team_rest` gives
`days_rest`, `matches_last_7d`/`_14d`, `prev_competition`, `prev_was_european`
and `after_long_break`.

## Known limits

- **Small dataset.** 2026/27 is 2 matchweeks old, so most history is 2025/26
  and only ~83 training rows have enough prior form to be usable. It grows
  every week.
- **Promoted clubs** (Coventry, Hull, Ipswich) have 2 matches each.
  `matches_before` tells you how thin any number is.
- **Congestion doesn't show a clean effect yet** (query 11) — the most
  congested teams are also the best teams. Control for quality before treating
  fatigue as negative, or the feature reads backwards.
- **The API is undocumented.** No auth needed, but field names can change; the
  scraper warns rather than writing NULLs silently.
- Data is Premier League/Opta copyright — fine for your own analysis; check
  their terms before republishing.

## Game state, and why possession alone misleads

Possession and xG are published only as whole-match totals. That makes a side
that led for an hour and sat deep look identical to one that was outplayed.

Goal minutes fix this. `pl_match_goal` stores every goal with the minute it was
scored, and `v_match_game_state` turns those into minutes spent ahead, level and
behind. On the data collected so far:

| Game state | n | Possession | xG |
| --- | --- | --- | --- |
| Led 45+ minutes | 52 | 48.3% | 1.92 |
| Mostly level | 92 | 50.0% | 1.40 |
| Trailed 45+ minutes | 52 | 51.7% | 1.15 |

Teams that chase have *more* of the ball and create *less*. Raw possession
reads backwards until you condition on game state.

Two caveats worth knowing. Minutes are measured on a nominal 90 because
stoppage time is not published per match, so every match sits on the same scale
rather than a guessed one. And own goals are filed under the team they count
for, not the scorer's side - verified against 30 matches, where event counts
matched every stored scoreline.

## Midfielders

There are no per-player performance stats anywhere in this API - no player xG,
passes or tackles. What there is:

- `pl_lineup` - the starting XI and bench, with `line_index`: the band a player
  occupies in the formation. This matters because `position` says "Midfielder"
  for a holding player and a number 10 alike; in a 4-2-3-1 the holding pair are
  band 2 and the attacking three band 3.
- `v_player_minutes` - minutes played, derived from the XI and substitutions.
  Every team-match sums to exactly 11 x 90 = 990.
- `v_team_midfield` - the midfield unit per match, its formation, and
  `midfield_changes`: how many starting midfielders did not start the previous
  match.

Team-level midfield control lives in `pl_team_match`: `poss_won_mid_third`,
`passes_final_third`, `dispossessed`, `ball_recoveries`, `take_ons_won` and
others. These come free with the stats call that was already being made.

## Recency weighting

`load.training_set()` returns a `weight` column: an exponential recency weight
that halves every `half_life_days` (see `config.yaml`). Pass it as
`sample_weight` when fitting.

This is deliberately not a cutoff. A hard "current season only" rule says a
match 91 days ago is worthless and one 89 days ago is worth full price; decay
says neither, and keeps the rows. `training.season` controls the scope
independently, so you can widen it later without rewriting anything.

## Looking at the data

```
python app.py     # http://127.0.0.1:5000
```

Read-only, local only, no auth - it reads `DATABASE_URL` like everything else.
Five pages: **Overview** (row counts and integrity checks), **Teams** (rolling form,
click any column to sort), **Matches** (browse and drill into a single match),
**Fixtures** (the prediction targets with their pre-kickoff features), and
**Model** (what the modelling layer currently has to work with).

Every page is a thin wrapper over the views in `views.sql` - no business logic
lives in the web layer, so the UI cannot disagree with the modelling layer about
what a number means.

## Files

| File | Purpose |
| --- | --- |
| `features.py` | Which API stat maps to which column — single source of truth |
| `views.sql` | All modelling views |
| `main.py` | Entry point: `--dry-run`, `--refresh`, `--matches N` |
| `pl_api.py` | API client |
| `db.py` | Postgres schema + upserts |
| `queries.sql` | Health checks, form tables, training/prediction exports |
| `app.py` | Local read-only web UI (`python app.py`) |
| `templates/`, `static/` | Pages and stylesheet for the UI |
| `.github/workflows/scrape.yml` | The hourly job |
