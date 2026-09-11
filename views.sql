-- ===========================================================================
-- Views for prediction modelling (PostgreSQL).
--
-- The important one is v_match_features: one row per match, with each side's
-- form as it stood BEFORE kickoff. Every rolling window below is defined as
-- ROWS BETWEEN n PRECEDING AND 1 PRECEDING - the "AND 1 PRECEDING" is what
-- excludes the current match. Without it the match's own result would be part
-- of its own features, and a model trained on that scores brilliantly in
-- backtests and collapses on live fixtures.
--
-- DROP ... CASCADE before each CREATE: Postgres refuses to CREATE OR REPLACE a
-- view whose column list changed, and these are rebuilt on every run.
-- ===========================================================================

DROP VIEW IF EXISTS v_fixture_features CASCADE;
DROP VIEW IF EXISTS v_match_features CASCADE;
DROP VIEW IF EXISTS v_latest_team_stats CASCADE;
DROP VIEW IF EXISTS v_team_form_current CASCADE;
DROP VIEW IF EXISTS v_team_poss_venue_current CASCADE;
DROP VIEW IF EXISTS v_team_form CASCADE;
DROP VIEW IF EXISTS v_team_rest CASCADE;
DROP VIEW IF EXISTS v_h2h_prior CASCADE;
DROP VIEW IF EXISTS v_h2h CASCADE;
DROP VIEW IF EXISTS v_team_match CASCADE;
DROP VIEW IF EXISTS v_match_game_state CASCADE;
DROP VIEW IF EXISTS v_team_midfield CASCADE;
DROP VIEW IF EXISTS v_player_minutes CASCADE;


-- ---------------------------------------------------------------------------
-- 1. v_team_match - a team's row with the opponent's full stat line attached.
--    Gives "against" values for every stat, not just the denormalised few.
-- ---------------------------------------------------------------------------
CREATE VIEW v_team_match AS
SELECT s.competition, s.match_id, s.kickoff, s.season, s.match_week,
       s.team_id, t.name AS team_name, t.abbr AS team_abbr,
       s.opponent_id, o.name AS opponent_name, o.abbr AS opponent_abbr,
       s.is_home, s.result, s.points,
       s.goals AS goals_for, s.goals_against,
       s.xg    AS xg_for,    s.xg_against,
       s.xgot  AS xgot_for,  opp.xgot AS xgot_against,
       s.possession AS possession_for, s.possession_against,
       s.shots AS shots_for, s.shots_against,
       s.shots_on_target AS shots_on_target_for, s.shots_on_target_against,
       s.big_chances_scored + s.big_chances_missed AS big_chances_for,
       opp.big_chances_scored + opp.big_chances_missed AS big_chances_against,
       s.corners AS corners_for, opp.corners AS corners_against,
       s.passes, s.passes_accurate,
       s.tackles, s.tackles_won, s.interceptions, s.clearances, s.blocks,
       s.saves, s.duels_won, s.aerials_won, s.poss_won_att_third,
       s.errors_lead_to_shot, s.fouls, s.yellows, s.reds, s.offsides,
       s.touches, s.touches_opp_box, s.pen_area_entries, s.final_third_entries
FROM pl_team_match s
JOIN pl_team_match opp
  ON opp.match_id = s.match_id AND opp.team_id = s.opponent_id
LEFT JOIN pl_teams t ON t.team_id = s.team_id
LEFT JOIN pl_teams o ON o.team_id = s.opponent_id;


-- ---------------------------------------------------------------------------
-- 2. v_team_rest - real rest days and fixture congestion.
--
--    Built from pl_team_appearance, which holds EVERY competitive fixture a
--    club plays, not just league games. A side playing Thursday in Europe and
--    Sunday in the league has 3 days off; a league-only calendar would claim
--    7 and the fatigue signal would read backwards.
--
--    Scheduled fixtures are in the table too, so upcoming matches get a rest
--    figure from the same window.
--
--    The congestion windows count CALENDAR DAYS, not elapsed time: ordering by
--    a day number rather than the timestamp. With an INTERVAL '14 days' frame,
--    a match exactly a fortnight earlier would fall in or out of the window
--    depending on kickoff time - a 12:30 game counting but a 17:30 one not.
--    Whole days make "played in the previous 14 days" mean what it says.
-- ---------------------------------------------------------------------------
CREATE VIEW v_team_rest AS
SELECT a.match_id, a.team_id, a.kickoff,
       a.competition_id, a.competition,
       (a.kickoff::date - (LAG(a.kickoff) OVER w_ord)::date) AS days_rest,
       LAG(a.competition) OVER w_ord                         AS prev_competition,
       (LAG(a.competition_id) OVER w_ord IN ('5','6','1125')) AS prev_was_european,
       -- A gap this large is a summer or winter break, not recovery. Left
       -- visible rather than nulled so you can decide what to do with it.
       ((a.kickoff::date - (LAG(a.kickoff) OVER w_ord)::date) > 45) AS after_long_break,
       COUNT(*) OVER w7  AS matches_last_7d,
       COUNT(*) OVER w14 AS matches_last_14d
FROM pl_team_appearance a
WINDOW
    w_ord AS (PARTITION BY a.team_id ORDER BY a.kickoff),
    w7    AS (PARTITION BY a.team_id ORDER BY (a.kickoff::date - DATE '2000-01-01')
              RANGE BETWEEN 7 PRECEDING AND 1 PRECEDING),
    w14   AS (PARTITION BY a.team_id ORDER BY (a.kickoff::date - DATE '2000-01-01')
              RANGE BETWEEN 14 PRECEDING AND 1 PRECEDING);


-- ---------------------------------------------------------------------------
-- 3. v_team_form - pre-match rolling form over the previous 5 and 10 matches.
--    Every column here describes the team as it was BEFORE this match.
--    matches_before tells you how much history backs the numbers: treat rows
--    with fewer than about 5 as thin rather than dropping them blindly.
-- ---------------------------------------------------------------------------
CREATE VIEW v_team_form AS
SELECT
    s.match_id, s.team_id, s.opponent_id, s.is_home, s.kickoff, s.season,
    s.result, s.points, s.goals, s.goals_against, s.xg, s.xg_against,

    COUNT(*) OVER w_all AS matches_before,

    AVG(s.xg)                OVER w5  AS xg_for_l5,
    AVG(s.xg_against)        OVER w5  AS xg_against_l5,
    AVG(s.xg - s.xg_against) OVER w5  AS xg_diff_l5,
    AVG(s.goals)             OVER w5  AS goals_for_l5,
    AVG(s.goals_against)     OVER w5  AS goals_against_l5,
    AVG(s.possession)        OVER w5  AS possession_l5,
    AVG(s.shots)             OVER w5  AS shots_l5,
    AVG(s.shots_on_target)   OVER w5  AS sot_l5,
    AVG(s.xgot)              OVER w5  AS xgot_l5,
    AVG(s.corners)           OVER w5  AS corners_l5,
    AVG(s.points)            OVER w5  AS ppg_l5,

    AVG(s.xg)                OVER w10 AS xg_for_l10,
    AVG(s.xg_against)        OVER w10 AS xg_against_l10,
    AVG(s.xg - s.xg_against) OVER w10 AS xg_diff_l10,
    AVG(s.goals)             OVER w10 AS goals_for_l10,
    AVG(s.goals_against)     OVER w10 AS goals_against_l10,
    AVG(s.possession)        OVER w10 AS possession_l10,
    AVG(s.points)            OVER w10 AS ppg_l10,

    -- Finishing luck: goals minus the chances' worth. Tends to regress, so a
    -- large positive value often means a team is due a correction.
    AVG(s.goals - s.xg)                 OVER w10 AS finishing_gap_l10,
    AVG(s.goals_against - s.xg_against) OVER w10 AS keeping_gap_l10,

    -- Same-venue form: home and away behaviour differ enough that blended
    -- form hides it.
    AVG(s.xg)         OVER w_venue AS xg_for_venue_l5,
    AVG(s.xg_against) OVER w_venue AS xg_against_venue_l5,
    AVG(s.points)     OVER w_venue AS ppg_venue_l5,
    AVG(s.possession) OVER w_venue AS possession_venue_l5,

    -- --- inputs for predicting possession -----------------------------------
    -- Possession is zero-sum inside a match, so "possession conceded" is just
    -- 100 minus a team's own and carries no extra information. What does add
    -- something is HOW a side holds the ball, since two teams on 55% can get
    -- there by opposite routes - patient short passing, or long balls that
    -- keep coming back.
    AVG(s.passes)                OVER w5  AS passes_l5,
    AVG(s.passes_accurate)       OVER w5  AS passes_acc_l5,
    AVG(s.touches)               OVER w5  AS touches_l5,
    AVG(s.long_own_to_opp)       OVER w5  AS long_balls_l5,
    AVG(s.poss_lost_ctrl)        OVER w5  AS poss_lost_ctrl_l5,
    AVG(s.dispossessed)          OVER w5  AS dispossessed_l5,
    AVG(s.ball_recoveries)       OVER w5  AS ball_recoveries_l5,
    AVG(s.poss_won_mid_third)    OVER w5  AS poss_won_mid_third_l5,
    AVG(s.passes_final_third)    OVER w5  AS passes_final_third_l5,
    AVG(s.possession)            OVER w20 AS possession_l20,

    -- Pass accuracy drives possession retention more directly than volume:
    -- a misplaced pass is a turnover, and a turnover is possession lost.
    CASE WHEN AVG(s.passes) OVER w5 > 0
         THEN AVG(s.passes_accurate) OVER w5 / NULLIF(AVG(s.passes) OVER w5, 0)
    END AS pass_accuracy_l5,

    -- League-only gap. The real rest figure comes from v_team_rest, which
    -- counts European and cup fixtures too.
    (s.kickoff::date - (LAG(s.kickoff) OVER w_order)::date) AS days_rest_league
FROM pl_team_match s
WINDOW
    w_order AS (PARTITION BY s.team_id ORDER BY s.kickoff),
    w_all   AS (PARTITION BY s.team_id ORDER BY s.kickoff
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
    w5      AS (PARTITION BY s.team_id ORDER BY s.kickoff
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
    w10     AS (PARTITION BY s.team_id ORDER BY s.kickoff
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
    -- Possession is a far more stable team trait than results are, so it
    -- rewards a longer window than form metrics do - the extra history is
    -- signal here, where for xG it would mostly be staleness.
    w20     AS (PARTITION BY s.team_id ORDER BY s.kickoff
                ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
    w_venue AS (PARTITION BY s.team_id, s.is_home ORDER BY s.kickoff
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING);


-- ---------------------------------------------------------------------------
-- 4. v_h2h - head-to-head record between two clubs, one row per ordered pair.
--    Read as "team_id against opponent_id".
-- ---------------------------------------------------------------------------
CREATE VIEW v_h2h AS
SELECT s.team_id, s.opponent_id,
       COUNT(*)                                        AS meetings,
       COUNT(*) FILTER (WHERE s.result = 'W')          AS wins,
       COUNT(*) FILTER (WHERE s.result = 'D')          AS draws,
       COUNT(*) FILTER (WHERE s.result = 'L')          AS losses,
       ROUND(AVG(s.points), 2)                         AS ppg,
       ROUND(AVG(s.goals), 2)                          AS goals_for_avg,
       ROUND(AVG(s.goals_against), 2)                  AS goals_against_avg,
       ROUND(AVG(s.xg), 3)                             AS xg_for_avg,
       ROUND(AVG(s.xg_against), 3)                     AS xg_against_avg,
       ROUND(AVG(s.possession), 1)                     AS possession_avg,
       MAX(s.kickoff)                                  AS last_meeting
FROM pl_team_match s
GROUP BY s.team_id, s.opponent_id;


-- ---------------------------------------------------------------------------
-- 4c. v_h2h_prior - head-to-head record from PREVIOUS meetings only.
--
--     v_h2h below aggregates every stored meeting between two clubs with no
--     regard for when they happened, which is correct for a fixture that has
--     not been played (all meetings are genuinely in the past) and badly wrong
--     as a training feature: the average includes the match being predicted.
--     With only one or two meetings per pair, "their h2h possession average"
--     is then essentially that match's own possession handed back as a
--     feature. It correlated 0.974 with the target before this view existed.
--
--     Same UNBOUNDED PRECEDING AND 1 PRECEDING frame as every other window
--     here, for the same reason.
-- ---------------------------------------------------------------------------
CREATE VIEW v_h2h_prior AS
SELECT s.match_id, s.team_id, s.opponent_id,
       COUNT(*)          OVER w AS meetings,
       AVG(s.points)     OVER w AS ppg,
       AVG(s.goals)      OVER w AS goals_for_avg,
       AVG(s.xg)         OVER w AS xg_for_avg,
       AVG(s.possession) OVER w AS possession_avg
FROM pl_team_match s
WINDOW w AS (PARTITION BY s.team_id, s.opponent_id ORDER BY s.kickoff
             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING);


-- ---------------------------------------------------------------------------
-- 4b. v_match_game_state - how long each side spent ahead, level and behind.
--
-- Why this exists: possession and xG are published only as whole-match totals,
-- so a side that led for an hour and sat deep looks identical in the raw
-- numbers to one that was outplayed. It is not. Goal minutes let us measure
-- the context those totals were accumulated in.
--
-- The segmentation walks the goals in order and treats the gap between
-- consecutive goals as an interval held at the score before the later one.
-- The final interval runs to a nominal 90 - stoppage time is not published
-- per match, so every match is measured on the same scale rather than a
-- guessed one. Goals in stoppage time are clamped to 90 so an interval can
-- never come out negative.
-- ---------------------------------------------------------------------------
CREATE VIEW v_match_game_state AS
WITH scored AS (
    -- Every goal, with its running effect on the scoreline, per match.
    SELECT g.match_id,
           LEAST(g.minute, 90)::int AS minute,
           g.team_id
    FROM pl_match_goal g
),
sides AS (
    -- One row per (match, team) we want a verdict for.
    SELECT match_id, team_id FROM pl_team_match
),
events AS (
    -- For each side, each goal becomes a boundary with the margin AFTER it.
    SELECT s.match_id, s.team_id, sc.minute,
           SUM(CASE WHEN sc.team_id = s.team_id THEN 1 ELSE -1 END)
               OVER (PARTITION BY s.match_id, s.team_id
                     ORDER BY sc.minute, sc.team_id
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS margin
    FROM sides s
    JOIN scored sc ON sc.match_id = s.match_id
),
segments AS (
    -- Kickoff to the first goal is always level; then each goal opens a
    -- segment running to the next goal, or to minute 90.
    --
    -- This half is driven off `sides`, not `events`, so a goalless match still
    -- produces a row. Deriving it from the goals would make a 0-0 vanish from
    -- the view entirely rather than come back as 90 minutes level.
    SELECT s.match_id, s.team_id, 0 AS margin, 0 AS from_min,
           COALESCE((SELECT MIN(e.minute) FROM events e
                     WHERE e.match_id = s.match_id
                       AND e.team_id = s.team_id), 90) AS to_min
    FROM sides s
    UNION ALL
    SELECT match_id, team_id, margin, minute AS from_min,
           COALESCE(LEAD(minute) OVER (PARTITION BY match_id, team_id
                                       ORDER BY minute), 90) AS to_min
    FROM events
)
-- COALESCE to 0, not NULL: a side that was never ahead spent zero minutes
-- ahead, which is a number. Left as NULL, AVG() would skip those matches and
-- report the average minutes-ahead of only the teams that ever led - the same
-- trap features.py avoids by coalescing absent count stats to 0.
SELECT match_id, team_id,
       COALESCE(SUM(GREATEST(to_min - from_min, 0))
                FILTER (WHERE margin > 0), 0)::int AS minutes_ahead,
       COALESCE(SUM(GREATEST(to_min - from_min, 0))
                FILTER (WHERE margin = 0), 0)::int AS minutes_level,
       COALESCE(SUM(GREATEST(to_min - from_min, 0))
                FILTER (WHERE margin < 0), 0)::int AS minutes_behind
FROM segments
GROUP BY match_id, team_id;


-- ---------------------------------------------------------------------------
-- 5. v_match_features - THE TRAINING TABLE (completed matches only).
--    One row per played match: each side's form as it stood BEFORE kickoff,
--    plus the actual outcome as the label.
--
--    Scheduled fixtures are deliberately NOT here. They have no pl_team_match
--    row to hang a window function on, so every feature would come out NULL.
--    Predict with v_fixture_features instead - same feature names, fed from
--    each team's current form.
-- ---------------------------------------------------------------------------
CREATE VIEW v_match_features AS
SELECT
    m.competition,
    m.match_id, m.kickoff, m.season, m.match_week, m.period,
    m.home_team_id, ht.name AS home_team, m.away_team_id, at.name AS away_team,

    m.home_score, m.away_score,
    CASE WHEN m.home_score IS NULL THEN NULL
         WHEN m.home_score > m.away_score THEN 'H'
         WHEN m.home_score < m.away_score THEN 'A'
         ELSE 'D' END                     AS outcome,
    m.home_score + m.away_score           AS total_goals,

    -- --- THE TARGET ---------------------------------------------------------
    -- Possession is zero-sum inside a match, so home_possession alone defines
    -- the result: away is 100 minus it. Train on the one column and derive the
    -- other, rather than fitting two models that can disagree.
    hs.possession AS home_possession,
    as_.possession AS away_possession,

    -- Context for the target, NOT features. Minutes spent ahead or behind are
    -- only known after the whistle, so feeding them to a model that predicts
    -- possession would be leakage of the plainest kind. They are here to
    -- explain residuals: a match settled early is inherently less predictable,
    -- because the leading side stops trying to keep the ball.
    hgs.minutes_ahead  AS home_minutes_ahead_post,
    hgs.minutes_level  AS home_minutes_level_post,
    hgs.minutes_behind AS home_minutes_behind_post,

    h.matches_before AS home_matches_before,
    h.xg_for_l5 AS home_xg_l5, h.xg_against_l5 AS home_xga_l5,
    h.xg_diff_l5 AS home_xgd_l5, h.ppg_l5 AS home_ppg_l5,
    h.possession_l5 AS home_poss_l5, h.shots_l5 AS home_shots_l5,
    h.sot_l5 AS home_sot_l5, h.corners_l5 AS home_corners_l5,
    h.xg_for_l10 AS home_xg_l10, h.xg_against_l10 AS home_xga_l10,
    h.ppg_l10 AS home_ppg_l10, h.finishing_gap_l10 AS home_finishing_gap,
    h.xg_for_venue_l5 AS home_xg_home_l5, h.ppg_venue_l5 AS home_ppg_home_l5,

    a.matches_before AS away_matches_before,
    a.xg_for_l5 AS away_xg_l5, a.xg_against_l5 AS away_xga_l5,
    a.xg_diff_l5 AS away_xgd_l5, a.ppg_l5 AS away_ppg_l5,
    a.possession_l5 AS away_poss_l5, a.shots_l5 AS away_shots_l5,
    a.sot_l5 AS away_sot_l5, a.corners_l5 AS away_corners_l5,
    a.xg_for_l10 AS away_xg_l10, a.xg_against_l10 AS away_xga_l10,
    a.ppg_l10 AS away_ppg_l10, a.finishing_gap_l10 AS away_finishing_gap,
    a.xg_for_venue_l5 AS away_xg_away_l5, a.ppg_venue_l5 AS away_ppg_away_l5,

    -- --- possession inputs, both sides --------------------------------------
    h.possession_l10 AS home_poss_l10, a.possession_l10 AS away_poss_l10,
    h.possession_l20 AS home_poss_l20, a.possession_l20 AS away_poss_l20,
    h.possession_venue_l5 AS home_poss_home_l5,
    a.possession_venue_l5 AS away_poss_away_l5,
    h.pass_accuracy_l5 AS home_pass_acc_l5,
    a.pass_accuracy_l5 AS away_pass_acc_l5,
    h.passes_l5 AS home_passes_l5, a.passes_l5 AS away_passes_l5,
    h.touches_l5 AS home_touches_l5, a.touches_l5 AS away_touches_l5,
    h.long_balls_l5 AS home_long_balls_l5, a.long_balls_l5 AS away_long_balls_l5,
    h.poss_lost_ctrl_l5 AS home_poss_lost_l5,
    a.poss_lost_ctrl_l5 AS away_poss_lost_l5,
    h.dispossessed_l5 AS home_dispossessed_l5,
    a.dispossessed_l5 AS away_dispossessed_l5,
    h.ball_recoveries_l5 AS home_recoveries_l5,
    a.ball_recoveries_l5 AS away_recoveries_l5,
    h.poss_won_mid_third_l5 AS home_poss_won_mid_l5,
    a.poss_won_mid_third_l5 AS away_poss_won_mid_l5,
    h.passes_final_third_l5 AS home_passes_f3_l5,
    a.passes_final_third_l5 AS away_passes_f3_l5,

    -- The single most informative construction: possession is RELATIVE. Two
    -- sides averaging 60% cannot both have 60% against each other, so the gap
    -- between their averages matters more than either number alone.
    h.possession_l5 - a.possession_l5 AS poss_gap_l5,
    h.possession_l10 - a.possession_l10 AS poss_gap_l10,

    -- The naive prediction, carried as a feature so a model has to beat it
    -- rather than rediscover it: split the difference between what the home
    -- side usually takes and what the away side usually concedes (100 minus
    -- theirs), which for zero-sum possession reduces to the midpoint.
    (h.possession_l5 + (100 - a.possession_l5)) / 2.0 AS poss_naive_l5,

    -- Real rest, counting European and cup fixtures.
    hr.days_rest         AS home_days_rest,
    ar.days_rest         AS away_days_rest,
    hr.matches_last_14d  AS home_matches_last_14d,
    ar.matches_last_14d  AS away_matches_last_14d,
    hr.prev_was_european AS home_prev_european,
    ar.prev_was_european AS away_prev_european,
    hr.after_long_break  AS home_after_break,
    ar.after_long_break  AS away_after_break,

    -- Differentials: usually more predictive than the raw pair, and they save
    -- the model having to learn the subtraction.
    h.xg_diff_l5 - a.xg_diff_l5    AS xgd_edge_l5,
    h.ppg_l5     - a.ppg_l5        AS ppg_edge_l5,
    h.xg_for_l5  - a.xg_against_l5 AS home_attack_vs_away_defence,
    a.xg_for_l5  - h.xg_against_l5 AS away_attack_vs_home_defence,

    hh.meetings AS h2h_meetings, hh.ppg AS h2h_home_ppg,
    hh.goals_for_avg AS h2h_home_goals_avg, hh.xg_for_avg AS h2h_home_xg_avg,
    hh.possession_avg AS h2h_home_poss_avg
FROM pl_matches m
LEFT JOIN v_team_form h  ON h.match_id = m.match_id AND h.team_id = m.home_team_id
LEFT JOIN v_team_form a  ON a.match_id = m.match_id AND a.team_id = m.away_team_id
LEFT JOIN pl_teams ht    ON ht.team_id = m.home_team_id
LEFT JOIN pl_teams at    ON at.team_id = m.away_team_id
LEFT JOIN v_h2h_prior hh ON hh.match_id = m.match_id
                        AND hh.team_id = m.home_team_id
LEFT JOIN v_team_rest hr ON hr.match_id = m.match_id AND hr.team_id = m.home_team_id
LEFT JOIN v_team_rest ar ON ar.match_id = m.match_id AND ar.team_id = m.away_team_id
-- The target, and the post-match context used only to explain residuals.
LEFT JOIN pl_team_match hs  ON hs.match_id = m.match_id
                           AND hs.team_id = m.home_team_id
LEFT JOIN pl_team_match as_ ON as_.match_id = m.match_id
                           AND as_.team_id = m.away_team_id
LEFT JOIN v_match_game_state hgs ON hgs.match_id = m.match_id
                                AND hgs.team_id = m.home_team_id
WHERE m.period = 'FullTime';


-- ---------------------------------------------------------------------------
-- 6. v_team_form_current - each team's form as of right now.
--    Same measures as v_team_form, but the windows INCLUDE the latest match
--    (CURRENT ROW rather than 1 PRECEDING), because for a fixture that has not
--    been played every completed match is legitimately in the past.
-- ---------------------------------------------------------------------------
CREATE VIEW v_team_form_current AS
SELECT competition, team_id, last_played, matches_used,
       xg_for_l5, xg_against_l5, xg_diff_l5, goals_for_l5, goals_against_l5,
       possession_l5, shots_l5, sot_l5, corners_l5, ppg_l5,
       xg_for_l10, xg_against_l10, ppg_l10, finishing_gap_l10,
       -- Possession inputs. These must mirror v_team_form exactly, or a model
       -- trained on that view cannot score a fixture from this one.
       possession_l10, possession_l20,
       pass_accuracy_l5, passes_l5, touches_l5, long_balls_l5,
       poss_lost_ctrl_l5, dispossessed_l5, ball_recoveries_l5,
       poss_won_mid_third_l5, passes_final_third_l5
FROM (
    SELECT s.competition, s.team_id,
           s.kickoff AS last_played,
           COUNT(*)                  OVER w5  AS matches_used,
           AVG(s.xg)                 OVER w5  AS xg_for_l5,
           AVG(s.xg_against)         OVER w5  AS xg_against_l5,
           AVG(s.xg - s.xg_against)  OVER w5  AS xg_diff_l5,
           AVG(s.goals)              OVER w5  AS goals_for_l5,
           AVG(s.goals_against)      OVER w5  AS goals_against_l5,
           AVG(s.possession)         OVER w5  AS possession_l5,
           AVG(s.shots)              OVER w5  AS shots_l5,
           AVG(s.shots_on_target)    OVER w5  AS sot_l5,
           AVG(s.corners)            OVER w5  AS corners_l5,
           AVG(s.points)             OVER w5  AS ppg_l5,
           AVG(s.xg)                 OVER w10 AS xg_for_l10,
           AVG(s.xg_against)         OVER w10 AS xg_against_l10,
           AVG(s.points)             OVER w10 AS ppg_l10,
           AVG(s.goals - s.xg)       OVER w10 AS finishing_gap_l10,

           AVG(s.possession)         OVER w10 AS possession_l10,
           AVG(s.possession)         OVER w20 AS possession_l20,
           AVG(s.passes)             OVER w5  AS passes_l5,
           AVG(s.touches)            OVER w5  AS touches_l5,
           AVG(s.long_own_to_opp)    OVER w5  AS long_balls_l5,
           AVG(s.poss_lost_ctrl)     OVER w5  AS poss_lost_ctrl_l5,
           AVG(s.dispossessed)       OVER w5  AS dispossessed_l5,
           AVG(s.ball_recoveries)    OVER w5  AS ball_recoveries_l5,
           AVG(s.poss_won_mid_third) OVER w5  AS poss_won_mid_third_l5,
           AVG(s.passes_final_third) OVER w5  AS passes_final_third_l5,
           CASE WHEN AVG(s.passes) OVER w5 > 0
                THEN AVG(s.passes_accurate) OVER w5
                     / NULLIF(AVG(s.passes) OVER w5, 0)
           END AS pass_accuracy_l5,

           ROW_NUMBER() OVER (PARTITION BY s.team_id
                              ORDER BY s.kickoff DESC) AS rn
    FROM pl_team_match s
    WINDOW
        w5  AS (PARTITION BY s.team_id ORDER BY s.kickoff
                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
        w10 AS (PARTITION BY s.team_id ORDER BY s.kickoff
                ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
        w20 AS (PARTITION BY s.team_id ORDER BY s.kickoff
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
) snap
WHERE snap.rn = 1;


-- ---------------------------------------------------------------------------
-- 6b. v_team_poss_venue_current - current home and away possession averages,
--     as two columns per team rather than one venue-dependent number.
--
--     v_team_form_current takes each team's most recent match, so a venue
--     average taken from it would describe whichever venue that match happened
--     to be at - away form used to predict a home fixture, half the time.
--     Keeping the last 5 at EACH venue separately lets v_fixture_features pick
--     the side it actually needs.
-- ---------------------------------------------------------------------------
CREATE VIEW v_team_poss_venue_current AS
SELECT team_id,
       MAX(poss_venue) FILTER (WHERE is_home = 1) AS possession_home_l5,
       MAX(poss_venue) FILTER (WHERE is_home = 0) AS possession_away_l5
FROM (
    SELECT s.team_id, s.is_home,
           AVG(s.possession) OVER w_venue AS poss_venue,
           ROW_NUMBER() OVER (PARTITION BY s.team_id, s.is_home
                              ORDER BY s.kickoff DESC) AS rn
    FROM pl_team_match s
    WINDOW w_venue AS (PARTITION BY s.team_id, s.is_home ORDER BY s.kickoff
                       ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
) v
WHERE v.rn = 1
GROUP BY team_id;


-- ---------------------------------------------------------------------------
-- 7. v_fixture_features - THE PREDICTION TABLE.
--    Upcoming matches with the same feature names v_match_features exposes,
--    so a model trained on that scores these directly.
-- ---------------------------------------------------------------------------
CREATE VIEW v_fixture_features AS
SELECT
    m.competition,
    m.match_id, m.kickoff, m.season, m.match_week,
    m.home_team_id, ht.name AS home_team,
    m.away_team_id, at.name AS away_team,

    h.matches_used AS home_matches_before,
    h.xg_for_l5 AS home_xg_l5, h.xg_against_l5 AS home_xga_l5,
    h.xg_diff_l5 AS home_xgd_l5, h.ppg_l5 AS home_ppg_l5,
    h.possession_l5 AS home_poss_l5, h.shots_l5 AS home_shots_l5,
    h.sot_l5 AS home_sot_l5, h.corners_l5 AS home_corners_l5,
    h.xg_for_l10 AS home_xg_l10, h.xg_against_l10 AS home_xga_l10,
    h.ppg_l10 AS home_ppg_l10, h.finishing_gap_l10 AS home_finishing_gap,

    a.matches_used AS away_matches_before,
    a.xg_for_l5 AS away_xg_l5, a.xg_against_l5 AS away_xga_l5,
    a.xg_diff_l5 AS away_xgd_l5, a.ppg_l5 AS away_ppg_l5,
    a.possession_l5 AS away_poss_l5, a.shots_l5 AS away_shots_l5,
    a.sot_l5 AS away_sot_l5, a.corners_l5 AS away_corners_l5,
    a.xg_for_l10 AS away_xg_l10, a.xg_against_l10 AS away_xga_l10,
    a.ppg_l10 AS away_ppg_l10, a.finishing_gap_l10 AS away_finishing_gap,

    -- --- possession inputs: names and meanings must match v_match_features ---
    h.possession_l10 AS home_poss_l10, a.possession_l10 AS away_poss_l10,
    h.possession_l20 AS home_poss_l20, a.possession_l20 AS away_poss_l20,
    -- The venue split, taken from the right side for this fixture: the home
    -- team's home average, the away team's away average.
    hv.possession_home_l5 AS home_poss_home_l5,
    av.possession_away_l5 AS away_poss_away_l5,
    h.pass_accuracy_l5 AS home_pass_acc_l5,
    a.pass_accuracy_l5 AS away_pass_acc_l5,
    h.passes_l5 AS home_passes_l5, a.passes_l5 AS away_passes_l5,
    h.touches_l5 AS home_touches_l5, a.touches_l5 AS away_touches_l5,
    h.long_balls_l5 AS home_long_balls_l5, a.long_balls_l5 AS away_long_balls_l5,
    h.poss_lost_ctrl_l5 AS home_poss_lost_l5,
    a.poss_lost_ctrl_l5 AS away_poss_lost_l5,
    h.dispossessed_l5 AS home_dispossessed_l5,
    a.dispossessed_l5 AS away_dispossessed_l5,
    h.ball_recoveries_l5 AS home_recoveries_l5,
    a.ball_recoveries_l5 AS away_recoveries_l5,
    h.poss_won_mid_third_l5 AS home_poss_won_mid_l5,
    a.poss_won_mid_third_l5 AS away_poss_won_mid_l5,
    h.passes_final_third_l5 AS home_passes_f3_l5,
    a.passes_final_third_l5 AS away_passes_f3_l5,

    h.possession_l5 - a.possession_l5 AS poss_gap_l5,
    h.possession_l10 - a.possession_l10 AS poss_gap_l10,
    (h.possession_l5 + (100 - a.possession_l5)) / 2.0 AS poss_naive_l5,

    h.xg_diff_l5 - a.xg_diff_l5    AS xgd_edge_l5,
    h.ppg_l5     - a.ppg_l5        AS ppg_edge_l5,
    h.xg_for_l5  - a.xg_against_l5 AS home_attack_vs_away_defence,
    a.xg_for_l5  - h.xg_against_l5 AS away_attack_vs_home_defence,

    hh.meetings AS h2h_meetings, hh.ppg AS h2h_home_ppg,
    hh.goals_for_avg AS h2h_home_goals_avg, hh.xg_for_avg AS h2h_home_xg_avg,
    hh.possession_avg AS h2h_home_poss_avg,

    COALESCE(hr.days_rest, m.kickoff::date - h.last_played::date) AS home_days_rest,
    COALESCE(ar.days_rest, m.kickoff::date - a.last_played::date) AS away_days_rest,
    hr.matches_last_14d  AS home_matches_last_14d,
    ar.matches_last_14d  AS away_matches_last_14d,
    hr.prev_was_european AS home_prev_european,
    ar.prev_was_european AS away_prev_european,
    hr.prev_competition  AS home_prev_competition,
    ar.prev_competition  AS away_prev_competition
FROM pl_matches m
LEFT JOIN v_team_form_current h ON h.team_id = m.home_team_id
LEFT JOIN v_team_form_current a ON a.team_id = m.away_team_id
LEFT JOIN v_team_poss_venue_current hv ON hv.team_id = m.home_team_id
LEFT JOIN v_team_poss_venue_current av ON av.team_id = m.away_team_id
LEFT JOIN pl_teams ht    ON ht.team_id = m.home_team_id
LEFT JOIN pl_teams at    ON at.team_id = m.away_team_id
-- An unplayed fixture has no pl_team_match row, so the match-keyed
-- v_h2h_prior would return NULL. Here the static view is correct:
-- every stored meeting genuinely IS in the past.
LEFT JOIN v_h2h hh       ON hh.team_id = m.home_team_id
                        AND hh.opponent_id = m.away_team_id
LEFT JOIN v_team_rest hr ON hr.match_id = m.match_id AND hr.team_id = m.home_team_id
LEFT JOIN v_team_rest ar ON ar.match_id = m.match_id AND ar.team_id = m.away_team_id
WHERE m.period <> 'FullTime';


-- ---------------------------------------------------------------------------
-- 8. v_latest_team_stats - each team's most recent completed match.
-- ---------------------------------------------------------------------------
CREATE VIEW v_latest_team_stats AS
SELECT v.*
FROM (
    SELECT s.*, ROW_NUMBER() OVER (PARTITION BY s.team_id
                                   ORDER BY s.kickoff DESC) AS rn
    FROM v_team_match s
) v
WHERE v.rn = 1;


-- ---------------------------------------------------------------------------
-- 10. v_player_minutes - minutes played, derived from the starting XI and subs.
--
-- Measured on the same nominal 90 as the game-state view, for the same reason.
-- A player who started and was never subbed off gets 90; one brought on in the
-- 68th gets 22. Red cards are not deducted - the API gives the card minute, so
-- that refinement is available later if it turns out to matter.
-- ---------------------------------------------------------------------------
CREATE VIEW v_player_minutes AS
SELECT l.match_id, l.team_id, l.player_id, l.position, l.line_index,
       l.formation, l.is_starter, l.is_captain,
       CASE
           -- Started: on from 0 until subbed off, or to the end.
           WHEN l.is_starter = 1
               THEN GREATEST(LEAST(COALESCE(off.minute, 90), 90), 0)
           -- Came on: from that minute until subbed off IN TURN, or to the end.
           -- Without the off leg, a substitute who is himself replaced is
           -- credited to the final whistle, which pushed team totals past the
           -- 11 x 90 = 990 ceiling.
           WHEN on_.minute IS NOT NULL
               THEN GREATEST(LEAST(COALESCE(off.minute, 90), 90)
                             - LEAST(on_.minute, 90), 0)
           ELSE 0                       -- unused substitute
       END AS minutes_played
FROM pl_lineup l
LEFT JOIN pl_match_sub off ON off.match_id = l.match_id
                          AND off.player_off_id = l.player_id
LEFT JOIN pl_match_sub on_ ON on_.match_id = l.match_id
                          AND on_.player_on_id = l.player_id;


-- ---------------------------------------------------------------------------
-- 11. v_team_midfield - the midfield unit each team fielded, per match.
--
-- The API's `position` says "Midfielder" for a holding player and a number 10
-- alike. line_index separates them: it is the band the player occupies in the
-- formation, counting from the keeper, so in a 4-2-3-1 the holding pair sit in
-- band 2 and the attacking three in band 3.
--
-- midfield_changes is the count of starting midfielders who did NOT start the
-- team's previous match - a settled midfield and a reshuffled one behave
-- differently, and this is the cheapest way to tell them apart.
-- ---------------------------------------------------------------------------
CREATE VIEW v_team_midfield AS
WITH starters AS (
    SELECT l.match_id, l.team_id, l.player_id, l.line_index, l.formation,
           tm.kickoff
    FROM pl_lineup l
    JOIN pl_team_match tm ON tm.match_id = l.match_id AND tm.team_id = l.team_id
    WHERE l.is_starter = 1
),
mids AS (
    -- Everything between the defence (band 1) and the furthest forward band.
    SELECT s.*,
           MAX(s.line_index) OVER (PARTITION BY s.match_id, s.team_id) AS top_band
    FROM starters s
),
per_match AS (
    SELECT match_id, team_id, kickoff, MIN(formation) AS formation,
           COUNT(*) FILTER (WHERE line_index BETWEEN 2 AND top_band - 1)
               AS midfielders,
           ARRAY_AGG(player_id ORDER BY player_id)
               FILTER (WHERE line_index BETWEEN 2 AND top_band - 1)
               AS midfield_ids
    FROM mids
    GROUP BY match_id, team_id, kickoff
),
with_prev AS (
    -- The LAG has to land in its own CTE: a window function cannot be
    -- referenced from the WHERE of the subquery that counts the changes.
    SELECT p.*,
           LAG(p.midfield_ids) OVER (PARTITION BY p.team_id ORDER BY p.kickoff)
               AS prev_midfield_ids
    FROM per_match p
)
SELECT w.*,
       CASE WHEN w.prev_midfield_ids IS NULL THEN NULL
            ELSE (SELECT COUNT(*) FROM UNNEST(w.midfield_ids) AS x
                  WHERE NOT x = ANY(w.prev_midfield_ids))
       END AS midfield_changes
FROM with_prev w;
