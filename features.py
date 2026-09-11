"""Single source of truth for which API stats become which database columns.

Both the Python scraper and php/pl_sync.php mirror this list - if you add a
stat here, add it to the PHP $STAT_MAP and to schema.sql too.

Names on the right are the keys in the /v3/matches/{id}/stats payload. A stat
is simply absent when it never happened (no red card, no save), so every one of
these is coalesced to 0 on the way in rather than stored as NULL - otherwise
AVG() would silently skip those matches and inflate the average.
"""

# column_name -> API key
STAT_MAP = {
    # --- attacking output ---
    "goals":               "goals",
    "xg":                  "expectedGoals",
    "xgot":                "expectedGoalsOnTarget",
    "xa":                  "expectedAssists",
    "shots":               "totalScoringAtt",
    "shots_on_target":     "ontargetScoringAtt",
    "shots_off_target":    "shotOffTarget",
    "shots_blocked":       "blockedScoringAtt",
    "shots_inside_box":    "attemptsIbox",
    "shots_outside_box":   "attemptsObox",
    "big_chances_scored":  "bigChanceScored",
    "big_chances_missed":  "bigChanceMissed",
    "big_chances_created": "bigChanceCreated",
    "corners":             "cornerTaken",
    "crosses":             "totalCross",
    "crosses_accurate":    "accurateCross",
    "pen_area_entries":    "penAreaEntries",
    "final_third_entries": "finalThirdEntries",
    "touches_opp_box":     "touchesInOppBox",

    # --- possession / passing ---
    "possession":          "possessionPercentage",
    "touches":             "touches",
    "passes":              "totalPass",
    "passes_accurate":     "accuratePass",

    # --- defending ---
    "tackles":             "totalTackle",
    "tackles_won":         "wonTackle",
    "interceptions":       "interception",
    "clearances":          "totalClearance",
    "blocks":              "outfielderBlock",
    "saves":               "saves",
    "duels_won":           "duelWon",
    "aerials_won":         "aerialWon",
    "poss_won_att_third":  "possWonAtt3rd",
    "errors_lead_to_shot": "errorLeadToShot",

    # --- discipline ---
    "fouls":               "fkFoulLost",
    "yellows":             "totalYelCard",
    "reds":                "totalRedCard",
    "offsides":            "totalOffside",

    # --- how the chances were created ---------------------------------------
    # A penalty is worth ~0.79 xG and is awarded semi-randomly, so a side's xG
    # average is noisier than it looks until penalties are separated out.
    # Non-penalty xG is the repeatable part; these columns let a view compute it.
    "goals_open_play":     "goalsOpenplay",
    "shots_open_play":     "attOpenplay",
    "pen_goals":           "attPenGoal",
    "pens_won":            "penaltyWon",
    "xg_freekick":         "expectedGoalsFreekick",
    "shots_freekick":      "attFreekickTotal",
    "goals_freekick":      "attFreekickGoal",
    "corners_won":         "wonCorners",
    "corners_lost":        "lostCorners",
    "corners_into_box":    "totalCornersIntobox",
    "corners_into_box_acc": "accurateCornersIntobox",

    # --- midfield control ---------------------------------------------------
    # The API has no per-player stats, so midfield quality has to be read from
    # team-level territory and turnover numbers. Where a side wins the ball back
    # matters more than how often: possWonAtt3rd is a press, possWonDef3rd is a
    # siege being survived.
    "poss_won_def_third":  "possWonDef3rd",
    "poss_won_mid_third":  "possWonMid3rd",
    "passes_final_third":  "totalFinalThirdPasses",
    "passes_final_third_acc": "successfulFinalThirdPasses",
    "passes_fwd_zone":     "totalFwdZonePass",
    "passes_fwd_zone_acc": "accurateFwdZonePass",
    "passes_back_zone":    "totalBackZonePass",
    "passes_back_zone_acc": "accurateBackZonePass",
    "passes_forward":      "fwdPass",
    "passes_backward":     "backwardPass",
    "long_balls_acc":      "accurateLongBalls",
    "long_own_to_opp":     "longPassOwnToOpp",
    "long_own_to_opp_acc": "longPassOwnToOppSuccess",
    "dispossessed":        "dispossessed",
    "poss_lost_all":       "possLostAll",
    "poss_lost_ctrl":      "possLostCtrl",
    "ball_recoveries":     "ballRecovery",
    "take_ons":            "totalContest",
    "take_ons_won":        "wonContest",

    # --- shot quality detail ---
    "shots_ibox_target":   "attIboxTarget",
    "shots_headed":        "attHdTotal",
    "goals_headed":        "attHdGoal",

    # --- defending detail (the losing side of duels, for win rates) ---
    "aerials_lost":        "aerialLost",
    "duels_lost":          "duelLost",
    "interceptions_won":   "interceptionWon",
    "clean_sheet":         "cleanSheet",
}

# Stats that are ratios/percentages rather than counts: absent means "unknown",
# not "zero", so these stay NULL when missing.
NON_COUNT_STATS = {"possession"}

# Kept denormalised on the team's own row because defensive form is needed
# constantly and a self-join for every query gets tedious. The full opponent
# picture is still available through the v_team_match view.
AGAINST_STATS = {
    "goals_against":      "goals",
    "xg_against":         "expectedGoals",
    "possession_against": "possessionPercentage",
    "shots_against":      "totalScoringAtt",
    "shots_on_target_against": "ontargetScoringAtt",
}

# Match-level context stored alongside the stats.
CONTEXT_COLUMNS = (
    # competition is written explicitly rather than left to the column default.
    # A default of 'PL' meant the first Bundesliga and LaLiga rows were all
    # stored as Premier League - silently, because a default cannot fail.
    "competition",
    "match_id", "team_id", "opponent_id", "is_home",
    "season", "match_week", "kickoff", "result", "points",
)

STAT_COLUMNS = tuple(STAT_MAP)
AGAINST_COLUMNS = tuple(AGAINST_STATS)
ALL_COLUMNS = CONTEXT_COLUMNS + STAT_COLUMNS + AGAINST_COLUMNS


# Columns holding fractional values; everything else is a whole-number count.
DECIMAL_COLUMNS = {
    "xg", "xgot", "xa", "possession", "xg_freekick",
    "xg_against", "possession_against",
}


def coerce(value, column):
    """Missing count stats mean zero; missing rates stay unknown."""
    if value is None:
        return None if column in NON_COUNT_STATS else 0
    return value


def sql_type(column):
    # Postgres has no UNSIGNED; SMALLINT (max 32767) comfortably covers every
    # count here - the largest is touches, around 900.
    if column in DECIMAL_COLUMNS:
        return "NUMERIC(8,4)"
    return "SMALLINT"


def stat_columns_ddl(indent="  "):
    """DDL fragment for every stat column, so the schema can never drift."""
    return "\n".join(f"{indent}{col} {sql_type(col)},"
                     for col in STAT_COLUMNS + AGAINST_COLUMNS)
