"""Czech for the e-sport pages (esport.html, esport_lines.html)."""
CS = {
    "E-sport": "E-sport",
    "E-sport: CS2 rounds": "E-sport: kola v CS2",
    "CS2: all lines": "CS2: všechny hranice",
    "No tips yet.": "Zatím žádné tipy.",
    "The CS2 model is being tested against Betano's round lines first: total rounds on a map, round handicaps and each team's rounds. Tips start here only once it beats those lines on matches that have been played, as with football and tennis.":
        "Model pro CS2 se nejdřív porovnává s hranicemi Betana na kola: celkový počet kol na mapě, "
        "handicap na kola a počet kol každého týmu. Tipy tu začnou, až když na odehraných zápasech "
        "tyto hranice porazí – stejně jako u fotbalu a tenisu.",
    "Tournament": "Turnaj",
    "Rounds share": "Podíl kol",
    "rounds share": "podíl kol",
    "The share of rounds the model expects the first team to win": "Kolik kol podle modelu vyhraje první tým",
    "Too few maps behind one of the teams": "Jeden z týmů má odehráno příliš málo map",
    "Too few maps behind one of the teams.": "Jeden z týmů má odehráno příliš málo map.",
    "No CS2 match on offer right now.": "Teď není v nabídce žádný zápas CS2.",
    "How the model works.": "Jak model funguje.",
    "Each team has a rating from the rounds it won in every S-, A- and B-tier CS2 match since 2024. From the two ratings the model gets the chance of winning a round, and from the CS2 rules (first to 13, overtime in blocks of six) the chance of every final score of a map - and so of any line on rounds. Results: <a href=\"https://liquipedia.net/counterstrike/\" target=\"_blank\" rel=\"noopener\">Liquipedia</a>, CC-BY-SA.":
        "Každý tým má hodnocení podle kol, která vyhrál ve všech zápasech CS2 úrovně S, A a B od roku 2024. "
        "Z hodnocení obou týmů model určí šanci na výhru kola a z pravidel CS2 (hraje se do 13, prodloužení "
        "po šesti kolech) šanci na každé konečné skóre mapy – a tedy na jakoukoli hranici na kola. "
        "Výsledky: <a href=\"https://liquipedia.net/counterstrike/\" target=\"_blank\" rel=\"noopener\">Liquipedia</a>, CC-BY-SA.",
    "Not tested against the bookmaker yet.": "Zatím neověřeno proti sázkové kanceláři.",
    "These are the model's prices, not tips. An edge here means only that the model disagrees with Betano; whether that disagreement is worth anything is what the settled lines will show.":
        "Toto jsou ceny modelu, ne tipy. Výhoda tu znamená jen to, že model nesouhlasí s Betanem; "
        "jestli ten nesouhlas má nějakou cenu, ukážou až vyhodnocené hranice.",
    "Largest edges": "Největší výhody",
    "Map": "Mapa",
    "Fair odds": "Férový kurz",
    "No priced CS2 line right now.": "Teď není oceněná žádná hranice CS2.",
    "%(n)s lines, the best-priced on each side": "%(n)s hranic, na každé straně ta nejlépe oceněná",
    "A team is not matched to Liquipedia yet.": "Tým zatím není spárovaný s Liquipedií.",
    "Total rounds": "Celkem kol",
    "Round handicap": "Handicap na kola",
    "Team rounds": "Kola týmu",
    "Overtime": "Prodloužení",
    "over": "více než",
    "under": "méně než",
    "yes": "ano",
    "no": "ne",
    "Model against Betano": "Model proti Betanu",
    "settled lines, lower is better": "vyhodnocené hranice, nižší je lepší",
    "Lines": "Hranice",
    "Model log-loss": "Log-loss modelu",
    "Betano log-loss (no margin)": "Log-loss Betana (bez marže)",
    "Better": "Lepší",
    "model": "model",
    "Lines the model rated +10%% or better: %(n)s settled, %(won)s won, %(pnl)s units at a flat unit (%(roi)s).":
        "Hranice s výhodou modelu +10 %% a více: %(n)s vyhodnocených, %(won)s vyhraných, %(pnl)s jednotek při stejném vkladu (%(roi)s).",
    "No CS2 line has settled yet.": "Zatím žádná vyhodnocená hranice CS2.",
    "Settled +10% lines": "Vyhodnocené hranice s výhodou +10 %",
    "CS2 tips": "Tipy na CS2",
    "CS2 results": "Výsledky tipů na CS2",
    "map": "mapa",
    "All maps": "Všechny mapy",
    "A new model, not yet proven.": "Nový model, zatím neprověřený.",
    "The CS2 tips started on 7 Nov 2026. The model beats a no-information baseline on past maps, but it has not yet been shown to beat Betano's own prices; its tips lean one way - on maps more lopsided than the bookmaker expects. Small stakes until the record says more.":
        "Tipy na CS2 začaly 7. 11. 2026. Model na odehraných mapách poráží odhad bez informací o týmech, "
        "ale zatím neprokázal, že porazí kurzy Betana; jeho tipy se kloní jedním směrem – k jednoznačnějším "
        "mapám, než čeká sázková kancelář. Dokud záznam neřekne víc, jen malé vklady.",
    "map not played, or no result in the data; not counted": "mapa se nehrála nebo chybí výsledek; nepočítá se",
    "Each tip is saved every time Betano's lines are collected and priced, and locked the moment its match starts &mdash; the database refuses any later change. Nothing here is recalculated; only the map's score is looked up, because that is a fact about the match. Tips are CS2 round lines at +10%% value or more, on the model's chance blended 3:1 with Betano's own (margin taken out), at most one per map. A line on a map that was not played is void.":
        "Každý tip se uloží pokaždé, když se načtou a ocení hranice Betana, a v okamžiku začátku zápasu se "
        "uzamkne &mdash; databáze pak žádnou změnu nepřijme. Nic se tu nepřepočítává; dohledává se jen skóre mapy, "
        "protože to je fakt o zápasu. Tipy jsou hranice na kola v CS2 s hodnotou +10 %% a více, ze šance modelu "
        "smíchané 3 : 1 se šancí Betana (bez marže), nejvýš jeden na mapu. Hranice na mapě, která se nehrála, je zrušená.",
    "<strong>Stake</strong> is in tenths of a unit: 10/10 is a full unit, whatever size you choose for one. It is quarter Kelly on the model's chance blended half and half with the bookmaker's, lower for long odds, and tips on the same match share one stake.":
        "<strong>Vklad</strong> je v desetinách jednotky: 10/10 je celá jednotka, ať si ji zvolíte jakkoli velkou. "
        "Počítá se jako čtvrtinový Kelly ze šance modelu smíchané napůl se šancí kanceláře, u vysokých kurzů je nižší "
        "a tipy na stejný zápas sdílejí jeden vklad.",
    "Results: <a href=\"https://liquipedia.net/counterstrike/\" target=\"_blank\" rel=\"noopener\">Liquipedia</a>, CC-BY-SA.":
        "Výsledky: <a href=\"https://liquipedia.net/counterstrike/\" target=\"_blank\" rel=\"noopener\">Liquipedia</a>, CC-BY-SA.",
}
