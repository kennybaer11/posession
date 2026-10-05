"""Czech for the tennis page (tennis.html) and the sport tabs in the menu."""
CS = {
    "Football": "Fotbal",
    "Tennis": "Tenis",
    "Tennis: aces and double faults": "Tenis: esa a dvojchyby",
    "Aces": "Esa",
    "Double faults": "Dvojchyby",
    "(match)": "(zápas)",
    "WTA lines, priced when they were entered.": "Hranice WTA, oceněné v okamžiku zadání.",
    "The model rates each player's ace and double-fault rate per serve point, on the surface and against this opponent, and simulates how many points each will serve. The probability and the advised side are saved when the line is priced; nothing here is recalculated afterwards. Results are filled in by the next morning's refresh. A retirement or walkover voids the line.":
        "Model odhaduje, jak často každá hráčka zahraje eso a dvojchybu na jeden podávaný míč – "
        "na daném povrchu a proti dané soupeřce – a simuluje, kolik míčů která odpodává. "
        "Pravděpodobnost a doporučená strana se uloží při ocenění hranice a později se nic "
        "nepřepočítává. Výsledky doplní ranní aktualizace. Skreč nebo kontumace hranici ruší.",
    "Model mean": "Průměr modelu",
    "P(over)": "P(nad)",
    "No open tennis line with an advised bet.": "Žádná otevřená tenisová hranice s doporučenou sázkou.",
    "No tennis line has settled yet.": "Zatím žádná vyhodnocená tenisová hranice.",
    "Void": "Zrušené",
    "Bookmaker": "Sázková kancelář",
    "All bookmakers": "Všechny kanceláře",
    "Manual": "Ručně",
    "Odds comparison": "Srovnání kurzů",
    "Tips": "Tipy",
    "Tenths of a unit: 10/10 is a full unit": "Desetiny jednotky: 10/10 je celá jednotka",
    "%(n)s tips with a stake": "%(n)s tipů s vkladem",
    "<strong>Stake</strong> is in tenths of a unit: 10/10 is a full unit, whatever size you choose for one. It is quarter Kelly on the model's chance blended half and half with the bookmaker's, lower for long odds, and tips on the same match share one stake. Tips given before 5 Oct 2026 have none.":
        "<strong>Vklad</strong> je v desetinách jednotky: 10/10 je celá jednotka, ať si ji zvolíte jakkoli velkou. "
        "Počítá se jako čtvrtinový Kelly ze šance modelu smíchané napůl se šancí kanceláře, u vysokých kurzů je nižší "
        "a tipy na stejný zápas sdílejí jeden vklad. Tipy z doby před 5. 10. 2026 vklad nemají.",
    "Tennis tips": "Tenisové tipy",
    "All lines": "Všechny hranice",
    "Tips, settled": "Tipy, vyhodnocené",
    "still updating until the match starts": "aktualizují se až do začátku zápasu",
    "Start": "Začátek",
    "Last time the tip was saved before the start": "Kdy byl tip naposledy uložen před začátkem",
    "started": "začal",
    "No open tip. New ones appear when the bookmakers' lines are collected and priced.": "Žádný otevřený tip. Nové přibudou, jakmile se stáhnou a ocení kurzy kanceláří.",
    "advice frozen at the start": "tip zmrazený při začátku zápasu",
    "P/L": "Zisk",
    "No tip has settled yet.": "Zatím žádný vyhodnocený tip.",
    "retired or walked over; stake returned": "skreč nebo kontumace; vklad se vrací",
    "placed": "vsazeno",
    "Withdrawn before the start": "Staženo před začátkem",
    "advised, then the odds moved; not counted; admin only": "doporučeno, pak se kurz změnil; nepočítá se; jen pro admina",
    "What the site advised, as it stood when each match started.": "Co web doporučil, přesně jak to stálo na začátku každého zápasu.",
    "Each tip is saved every time the bookmakers' lines are collected and priced, and locked the moment its match starts &mdash; the database refuses any later change. Nothing here is recalculated: a new model or a code fix changes the price list, never this record. Only the count of aces is looked up, because that is a fact about the match. Tips are aces only, at +10% value or more against the model; a retirement or walkover voids the bet.":
        "Každý tip se uloží při každém stažení a ocenění kurzů a zamkne se ve chvíli, kdy zápas začne &mdash; "
        "databáze pozdější změnu odmítne. Nic se tu nepřepočítává: nový model nebo oprava kódu změní ceník, "
        "nikdy tento záznam. Dohledává se jen počet es, protože to je fakt o zápase. Tipy jsou jen na esa, "
        "s výhodou aspoň +10 % proti modelu; skreč nebo kontumace sázku ruší.",
    "Placed": "Vsazeno",
    "I placed this bet (the side and price shown)": "Tuto sázku jsem podal (zobrazená strana a kurz)",
    "My bets, settled": "Moje sázky, vyhodnocené",
    "My P/L, 1 unit each": "Můj zisk, po 1 jednotce",
    "My bets, open": "Moje sázky, otevřené",
    "void": "zrušeno",
    "Could not save": "Nepodařilo se uložit",
    "All settled lines": "Všechny vyhodnocené hranice",
    "Tennis data": "Stav dat",
    "No upcoming match with ace or double-fault odds collected.": "Žádný nadcházející zápas se staženými kurzy na esa nebo dvojchyby.",
    "Whether the aces pipeline is alive. Betano is collected by the server every three hours; Chance.cz only when it is read in a browser session. The tour data feeds the ratings: the WTA's own API refreshes daily, the ATP comes from tennistourdata.com. All times are UTC.":
        "Jestli tenisová část běží. Betano stahuje server každé tři hodiny, Chance.cz jen při čtení v prohlížeči během sezení. "
        "Z dat okruhů se počítají hodnocení: WTA z jejího API každý den, ATP z tennistourdata.com. Všechny časy jsou v UTC.",
    "Bookmaker collections": "Stahování kurzů",
    "Last collected": "Naposledy staženo",
    "Runs, last 24h": "Běhů za 24 h",
    "Upcoming matches": "Nadcházející zápasy",
    "Players not matched": "Nespárovaní hráči",
    "Betano in red: more than four hours since the last collection, so at least one of the server's three-hourly runs stored nothing - see /home/app/logs/aces.log on the server.":
        "Betano červeně: od posledního stažení uběhly víc než čtyři hodiny, takže aspoň jeden tříhodinový běh na serveru nic neuložil – viz /home/app/logs/aces.log na serveru.",
    "Nothing collected yet.": "Zatím nic staženo.",
    "Advised, not started": "Doporučené, nezačaly",
    "Advised, awaiting result": "Doporučené, čekají na výsledek",
    "Advised, settled": "Doporučené, vyhodnocené",
    "Last priced": "Naposledy oceněno",
    "Tour data": "Data okruhů",
    "what the ratings are built from": "z čeho se počítají hodnocení",
    "Tour": "Okruh",
    "Completed": "Dohrané",
    "Latest match": "Poslední zápas",
    "Last 7 days": "Posledních 7 dní",
    "days ago": "dní zpět",
    "upcoming matches the model cannot price: no tour history under that name": "nadcházející zápasy, které model neocení: pod tímto jménem nemá historii",
    "every bookmaker's price beside the model's fair price; the best price per side in bold, green where it beats the model by 10% or more - aces only, the model is no better than a player's own average on double faults":
        "kurzy všech kanceláří vedle férového kurzu modelu; nejlepší kurz na každé straně tučně, zeleně tam, kde model poráží o 10 % a víc – jen esa, u dvojchyb model není lepší než prostý průměr hráčky",
    "best": "nejlepší",
    "no model price yet": "zatím bez ceny modelu",
    "Fair over": "Férový nad",
    "Fair under": "Férový pod",
    "Best EV": "Nejlepší EV",
    "retired or walked over; admin only": "skreč nebo kontumace; jen pro admina",
}
