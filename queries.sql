-- ===========================================================================
-- Premier League database (PostgreSQL) - checking, exploring, modelling.
-- Paste any of these into phpMyAdmin's SQL tab.
--
-- Tables:  pl_teams, pl_matches, pl_team_match
-- Views:   v_team_match (for/against), v_team_form (point-in-time form),
--          v_match_features (TRAINING), v_fixture_features (PREDICTION),
--          v_h2h, v_latest_team_stats, v_team_form_current
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. HEALTH CHECK
-- ---------------------------------------------------------------------------
SELECT 'teams'                AS item, COUNT(*) AS n FROM pl_teams
UNION ALL SELECT 'matches (all)',      COUNT(*) FROM pl_matches
UNION ALL SELECT 'matches played',     COUNT(*) FROM pl_matches WHERE period='FullTime'
UNION ALL SELECT 'fixtures upcoming',  COUNT(*) FROM pl_matches WHERE period<>'FullTime'
UNION ALL SELECT 'team-match rows',    COUNT(*) FROM pl_team_match
UNION ALL SELECT 'training rows',      COUNT(*) FROM v_match_features
UNION ALL SELECT 'fixtures w/ features', COUNT(*) FROM v_fixture_features
                                         WHERE home_xg_l5 IS NOT NULL
-- Every match must have BOTH teams stored, or that fixture's features break.
UNION ALL SELECT 'orphan rows (must be 0)',
       (SELECT COUNT(*) FROM pl_team_match s
         LEFT JOIN pl_team_match o
           ON o.match_id=s.match_id AND o.team_id=s.opponent_id
        WHERE o.match_id IS NULL)
UNION ALL SELECT 'possession != 100 (must be 0)',
       (SELECT COUNT(*) FROM pl_team_match
         WHERE ABS(possession + possession_against - 100) > 0.11);


-- ---------------------------------------------------------------------------
-- 2. LATEST MATCH FOR EACH TEAM  (the "current stats" view)
-- ---------------------------------------------------------------------------
SELECT team_name, kickoff::date AS played,
       CASE WHEN is_home=1 THEN 'H' ELSE 'A' END AS venue, opponent_name,
       goals_for || '-' || goals_against AS score, result,
       possession_for, possession_against, xg_for, xg_against,
       shots_for, shots_on_target_for, big_chances_for, corners_for
FROM v_latest_team_stats
ORDER BY kickoff DESC, team_name;


-- ---------------------------------------------------------------------------
-- 3. CURRENT FORM TABLE  (last 5 completed matches, inclusive)
-- ---------------------------------------------------------------------------
SELECT t.name AS team, c.matches_used AS mp,
       ROUND(c.ppg_l5,2)          AS ppg,
       ROUND(c.possession_l5,1)   AS poss,
       ROUND(c.xg_for_l5,2)       AS xg_for,
       ROUND(c.xg_against_l5,2)   AS xg_against,
       ROUND(c.xg_diff_l5,2)      AS xg_diff,
       ROUND(c.finishing_gap_l10,2) AS finishing_gap
FROM v_team_form_current c
JOIN pl_teams t ON t.team_id = c.team_id
ORDER BY xg_diff DESC;


-- ---------------------------------------------------------------------------
-- 4. NEXT FIXTURES WITH THEIR PREDICTION FEATURES
--    This is what you feed a model to predict. Same feature names as the
--    training view, so a model trained there scores these directly.
-- ---------------------------------------------------------------------------
SELECT kickoff::date AS d, home_team, away_team,
       ROUND(home_xg_l5,2)  AS h_xg,  ROUND(away_xg_l5,2)  AS a_xg,
       ROUND(home_xga_l5,2) AS h_xga, ROUND(away_xga_l5,2) AS a_xga,
       ROUND(xgd_edge_l5,2) AS xg_edge, ROUND(ppg_edge_l5,2) AS ppg_edge,
       home_matches_before AS h_n, away_matches_before AS a_n,
       h2h_meetings
FROM v_fixture_features
ORDER BY kickoff;


-- ---------------------------------------------------------------------------
-- 5. THE TRAINING SET
--    One row per played match, each side's form as it stood BEFORE kickoff,
--    with the real outcome as the label. Export this to CSV and model it.
--
--    The matches_before filter matters: early rows have almost no history
--    behind their "form", so they are noise rather than signal.
-- ---------------------------------------------------------------------------
SELECT kickoff, home_team, away_team, outcome, total_goals,
       home_xg_l5, home_xga_l5, home_ppg_l5, home_poss_l5, home_sot_l5,
       away_xg_l5, away_xga_l5, away_ppg_l5, away_poss_l5, away_sot_l5,
       xgd_edge_l5, ppg_edge_l5,
       home_attack_vs_away_defence, away_attack_vs_home_defence,
       home_finishing_gap, away_finishing_gap,
       home_days_rest, away_days_rest, h2h_home_ppg
FROM v_match_features
WHERE home_matches_before >= 3 AND away_matches_before >= 3
ORDER BY kickoff;


-- ---------------------------------------------------------------------------
-- 6. HEAD-TO-HEAD between two clubs
-- ---------------------------------------------------------------------------
SELECT ht.name AS team, at.name AS opponent,
       h.meetings, h.wins, h.draws, h.losses, h.ppg,
       h.goals_for_avg, h.goals_against_avg, h.xg_for_avg, h.xg_against_avg,
       h.last_meeting::date AS last_met
FROM v_h2h h
JOIN pl_teams ht ON ht.team_id = h.team_id
JOIN pl_teams at ON at.team_id = h.opponent_id
WHERE ht.abbr = 'ARS' AND at.abbr = 'MCI';


-- ---------------------------------------------------------------------------
-- 7. SANITY CHECK BEFORE YOU TRUST A MODEL
--    Does the pre-match xG edge actually relate to the result? If the win rate
--    does not climb across these bands, the feature is not carrying signal and
--    no amount of model tuning will rescue it.
-- ---------------------------------------------------------------------------
SELECT CASE
         WHEN xgd_edge_l5 < -0.5 THEN 'a. away much better'
         WHEN xgd_edge_l5 <  0   THEN 'b. away slightly better'
         WHEN xgd_edge_l5 <  0.5 THEN 'c. home slightly better'
         ELSE                         'd. home much better'
       END                              AS pre_match_edge,
       COUNT(*)                         AS matches,
       ROUND(AVG((outcome='H')::int)*100)      AS home_win_pct,
       ROUND(AVG((outcome='D')::int)*100)      AS draw_pct,
       ROUND(AVG((outcome='A')::int)*100)      AS away_win_pct,
       ROUND(AVG(total_goals),2)        AS avg_goals
FROM v_match_features
WHERE xgd_edge_l5 IS NOT NULL
GROUP BY pre_match_edge ORDER BY pre_match_edge;


-- ---------------------------------------------------------------------------
-- 8. ONE TEAM'S RECENT MATCHES, for/against
-- ---------------------------------------------------------------------------
SELECT kickoff::date AS played, CASE WHEN is_home=1 THEN 'H' ELSE 'A' END AS venue, opponent_name,
       goals_for || '-' || goals_against AS score, result,
       possession_for, possession_against, xg_for, xg_against,
       shots_for, shots_against, big_chances_for, big_chances_against
FROM v_team_match
WHERE team_abbr = 'ARS'
ORDER BY kickoff DESC LIMIT 10;


-- ---------------------------------------------------------------------------
-- 9. FRESHNESS - is the cron still running?
-- ---------------------------------------------------------------------------
SELECT season, COUNT(*) AS rows_stored,
       MAX(kickoff)   AS newest_match,
       MAX(last_seen) AS last_written
FROM pl_team_match GROUP BY season ORDER BY season DESC;


-- ---------------------------------------------------------------------------
-- 10. REST DAYS AND FIXTURE CONGESTION
--     days_rest counts EVERY competition, so a Thursday European tie followed
--     by a Sunday league game shows 3 days, not 7. Compare against
--     days_rest_league to see how much the league-only view was hiding.
-- ---------------------------------------------------------------------------
SELECT t.abbr, f.kickoff::date AS pl_match,
       f.days_rest_league AS league_only_gap,
       r.days_rest        AS true_rest,
       r.prev_competition AS came_from,
       r.prev_was_european AS from_europe,
       r.matches_last_14d AS played_last_14d,
       r.after_long_break AS post_break
FROM v_team_form f
JOIN pl_teams t ON t.team_id = f.team_id
LEFT JOIN v_team_rest r ON r.match_id = f.match_id AND r.team_id = f.team_id
WHERE t.abbr = 'ARS'
ORDER BY f.kickoff DESC;


-- ---------------------------------------------------------------------------
-- 11. DOES CONGESTION ACTUALLY COST ANYTHING?
--     Check before trusting it as a feature. Beware: European sides are both
--     the most congested AND the best teams, so a naive read understates the
--     effect. Control for team quality before drawing conclusions.
-- ---------------------------------------------------------------------------
SELECT home_matches_last_14d AS home_games_last_14d,
       COUNT(*)                      AS matches,
       ROUND(AVG((outcome='H')::int)*100)   AS home_win_pct,
       ROUND(AVG(home_days_rest), 1) AS avg_rest
FROM v_match_features
WHERE home_matches_last_14d IS NOT NULL
GROUP BY home_matches_last_14d ORDER BY home_matches_last_14d;
