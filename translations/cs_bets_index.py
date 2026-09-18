"""Czech for the Overview page (index.html), the Learning page (bets.html) and
the league tabs (_leaguetabs.html)."""
CS = {
    # -- league tabs ---------------------------------------------------------
    "All leagues": "Všechny ligy",

    # -- Overview (index.html) -----------------------------------------------
    "Matches stored": "Uložené zápasy",
    "Upcoming fixtures": "Nadcházející zápasy",
    "Team-match stat rows": "Řádky statistik tým–zápas",
    "Team appearances": "Starty týmů",
    "all competitions, drives rest days": "všechny soutěže, z nich se počítají dny odpočinku",
    "Data health": "Stav dat",
    "Rows missing xG": "Řádky bez xG",
    "none": "žádné",
    "Rows missing possession": "Řádky bez držení míče",
    "Mean possession": "Průměrné držení míče",
    "Zero-sum within a match, so this should sit on 50.00":
        "V rámci zápasu se sčítá na 100, takže by mělo vycházet přesně 50.00",
    "Matches without exactly 2 rows": "Zápasy, které nemají právě 2 řádky",
    "Every match must contribute one row per side": "Každý zápas musí mít jeden řádek za každý tým",
    "xG range": "Rozsah xG",
    "mean": "průměr",
    "Last scrape": "Poslední stažení",
    "Seasons": "Sezóny",
    "Season": "Sezóna",
    "Played": "Odehráno",
    "From": "Od",
    "To": "Do",
    "Coverage per team": "Pokrytí podle týmů",
    "fewest matches first, so gaps surface at the top": "nejméně zápasů nahoře, aby mezery byly hned vidět",
    "Team": "Tým",
    "Last played": "Naposledy hrál",
    "Latest matches": "Poslední zápasy",
    "Date": "Datum",
    "Match": "Zápas",
    "Score": "Skóre",
    "detail": "detail",

    # -- Learning (bets.html) ------------------------------------------------
    "<strong>How today's model would have done on every recorded line.</strong> This page is "
    "recalculated on every rebuild, so it improves as the model does &mdash; and for the same "
    "reason it is <em>not</em> a record of what the site advised: a model change can move a past "
    "bet from OVER to no bet. The unchangeable record of advice as given lives in the admin "
    "section, under Advice record. Use this page to learn whether the model is getting better; "
    "use that one to judge the advice.":
        "<strong>Jak by dnešní model dopadl na všech zaznamenaných hranicích.</strong> Stránka se "
        "přepočítává při každém sestavení, takže se zlepšuje spolu s modelem &mdash; a ze stejného "
        "důvodu <em>není</em> záznamem toho, co web doporučil: změna modelu může minulou sázku "
        "přesunout z VÍCE na nesázet. Neměnný záznam doporučení, jak byla skutečně dána, najdete "
        "na stránce Tipy. Tahle stránka ukazuje, jestli se model zlepšuje; "
        "podle té druhé posuzujte doporučení.",
    "<strong>How it is graded.</strong> Each match counts once: if the market moved and a second "
    "line was recorded, only the first is graded &mdash; the opening price the scraper exists to "
    "capture. And a settled line is graded with the prediction the model would have made "
    "<em>before kickoff</em>, fitted only on matches played earlier. Grading it with a model that "
    "has already seen the result flatters the record badly. When this was fixed on 14 Sep 2026, "
    "the bets settled by then read 71%% won and +30%% ROI with hindsight, and 60%% and +10%% without. "
    "Predictions come from the fitted model where a league has enough history for one, with "
    "each league's own error spread:":
        "<strong>Jak se hodnotí.</strong> Každý zápas se počítá jednou: pokud se trh pohnul a byla "
        "zaznamenána druhá hranice, hodnotí se jen ta první &mdash; otevírací kurz, kvůli kterému "
        "stahování kurzů existuje. Vyhodnocená hranice se navíc posuzuje předpovědí, kterou by model "
        "dal <em>před výkopem</em>, natrénovaný jen na dříve odehraných zápasech. Hodnotit ji "
        "modelem, který už výsledek viděl, záznam hrubě přikrášluje. Když se to 14. 9. 2026 "
        "opravilo, sázky vyhodnocené do té doby ukazovaly se zpětným pohledem 71%% výher a "
        "ROI +30%%, bez něj 60%% a +10%%. Předpovědi pocházejí z natrénovaného modelu tam, kde má "
        "liga dost historie, a s vlastním rozptylem chyby pro každou ligu:",
    "default": "výchozí",
    "A wider spread means less confidence in any single prediction, so the same gap to a "
    "line is worth less. Rows marked <sup class=\"warn\">*</sup> came from the naive midpoint "
    "instead, because that league cannot fit a model yet &mdash; see below the table.":
        "Větší rozptyl znamená menší důvěru v jednotlivou předpověď, takže stejný odstup od "
        "hranice má menší váhu. Řádky označené <sup class=\"warn\">*</sup> místo toho vycházejí "
        "z naivního odhadu (středu), protože pro tu ligu zatím model natrénovat nejde &mdash; viz "
        "pod tabulkou.",
    "Lines recorded": "Zaznamenané hranice",
    "Settled": "Vyhodnocené",
    "Backed by the model": "Model by vsadil",
    "positive edge only": "jen s kladnou výhodou",
    "Profit / loss (units)": "Zisk / ztráta (jednotky)",
    "Return on stake": "Návratnost vkladu",
    "on %(count)s bet &mdash; not a result": (
        "z %(count)s sázky &mdash; to není výsledek",
        "ze %(count)s sázek &mdash; to není výsledek",
        "z %(count)s sázek &mdash; to není výsledek",
    ),
    "Should you be betting this yet?": "Má už smysl na to sázet?",
    "Yes &mdash; the record now supports it.": "Ano &mdash; záznam to už podporuje.",
    "Not yet.": "Zatím ne.",
    "Bets the model actually backed, settled": "Vyhodnocené sázky, které model skutečně vsadil",
    "Won": "Vyhráno",
    "Breakeven at these prices": "Bod zvratu při těchto kurzech",
    "The average of 1/odds across the bets taken &mdash; the rate that merely breaks even":
        "Průměr 1/kurz přes uzavřené sázky &mdash; úspěšnost, která jen vyrovná náklady",
    "Standard errors clear of breakeven": "Směrodatných chyb nad bodem zvratu",
    "Below 2 the result is within what luck produces": "Pod 2 je výsledek v mezích toho, co dokáže štěstí",
    "<strong>The rule:</strong> bet when the model has beaten the market by more than luck "
    "explains &mdash; not when it claims an edge. A model's own edge estimate is a claim "
    "about itself; the only thing that can check it is a settled record. Two standard "
    "errors is the usual bar, and at these prices that means roughly 100&ndash;200 settled "
    "bets. That is not pessimism, it is what it costs to tell a real 5%% edge from a coin "
    "that landed well.":
        "<strong>Pravidlo:</strong> sázejte, až model porazí trh o víc, než vysvětlí štěstí "
        "&mdash; ne když si výhodu jen nárokuje. Odhad výhody od samotného modelu je tvrzení "
        "o sobě samém; ověřit ho může jen vyhodnocený záznam. Obvyklá laťka jsou dvě směrodatné "
        "chyby, což při těchto kurzech znamená zhruba 100&ndash;200 vyhodnocených sázek. Není to "
        "pesimismus, tolik stojí odlišit skutečnou 5%% výhodu od mince, která padla šťastně.",
    "You do <strong>not</strong> have to stake money to get there. Every recorded line is "
    "graded whether or not a bet was placed, so the record builds itself for free.":
        "Abyste se tam dostali, <strong>nemusíte</strong> vsázet peníze. Každá zaznamenaná "
        "hranice se vyhodnotí bez ohledu na to, jestli sázka proběhla, takže záznam roste zadarmo.",
    "%(n)s settled — far too few to conclude anything.":
        "Vyhodnoceno %(n)s — příliš málo na jakýkoli závěr.",
    "Detecting a real 5%% edge with any confidence takes something closer to 100–200 "
    "settled bets. Until then this page is a record, not a verdict, and a run of wins "
    "is as likely to be luck as skill.":
        "Spolehlivě odhalit skutečnou 5%% výhodu vyžaduje spíš 100–200 vyhodnocených sázek. "
        "Do té doby je tahle stránka záznam, ne verdikt, a série výher je stejně dobře štěstí "
        "jako dovednost.",
    "Note also that only %(both)s of %(total)s lines have "
    "<strong>both</strong> prices, so the bookmaker's margin cannot be stripped out of the "
    "rest &mdash; every edge below is measured against an inflated probability, which "
    "understates the true bar.":
        "Všimněte si také, že jen %(both)s z %(total)s hranic má <strong>oba</strong> kurzy, "
        "takže u ostatních nejde odečíst marži sázkové kanceláře &mdash; každá výhoda níže se "
        "měří proti nadsazené pravděpodobnosti, což skutečnou laťku podhodnocuje.",
    "Kickoff": "Výkop",
    "League": "Liga",
    "Line is about": "Hranice se týká",
    "Line": "Hranice",
    "Bet": "Sázka",
    "Odds": "Kurz",
    "P(side)": "P(strany)",
    "Edge": "Výhoda",
    "Stake": "Vklad",
    "Actual": "Skutečnost",
    "Result": "Výsledek",
    "OVER": "VÍCE",
    "UNDER": "MÉNĚ",
    "no bet": "nesázet",
    "No fitted model for this league yet - naive midpoint":
        "Pro tuto ligu zatím není natrénovaný model - naivní odhad (střed)",
    "skipped": "vynecháno",
    "pending": "čeká",
    "won": "výhra",
    "lost": "prohra",
    "%(count)s row did not come from a fitted model.": (
        "%(count)s řádek nepochází z natrénovaného modelu.",
        "%(count)s řádky nepocházejí z natrénovaného modelu.",
        "%(count)s řádků nepochází z natrénovaného modelu.",
    ),
    "Their league has too little history to fit one, "
    "so the figure is the naive midpoint &mdash; the side's own recent possession averaged "
    "against what its opponent concedes, on as few as two matches each. The midpoint pulls "
    "hard towards 50, so it understates a mismatch: a strong side away at a weak one reads "
    "lower than it should, and the edge against a bookmaker's line can come out the wrong "
    "way round entirely. Treat the Bet, Edge and Stake columns on these rows as unproven.":
        "Jejich liga má na natrénování modelu příliš krátkou historii, takže číslo je naivní "
        "odhad (střed) &mdash; nedávné držení míče týmu zprůměrované s tím, kolik míče nechává "
        "soupeř, a to i jen ze dvou zápasů každého. Střed silně táhne k 50, takže nerovnost "
        "podhodnocuje: silný tým venku u slabého vychází níž, než by měl, a výhoda proti hranici "
        "sázkové kanceláře může vyjít úplně obráceně. Sloupce Sázka, Výhoda a Vklad u těchto "
        "řádků berte jako neověřené.",
    "No lines recorded yet. Add them to <code>odds.txt</code> and the next run will import them.":
        "Zatím nejsou zaznamenané žádné hranice. Přidejte je do <code>odds.txt</code> a další "
        "běh je naimportuje.",
    "Adding lines": "Přidávání hranic",
    "Edit <code>odds.txt</code> in GitHub's web editor, paste a row, commit. The hourly run "
    "imports it. Columns are "
    "<code>date &middot; club &middot; club &middot; whose-possession &middot; line &middot; over &middot; under</code>, "
    "whitespace-separated, with <code>-</code> for a price you do not have. Club order does "
    "not matter. Use the abbreviations below, or names without spaces.":
        "Upravte <code>odds.txt</code> ve webovém editoru GitHubu, vložte řádek a commitněte. "
        "Hodinový běh ho naimportuje. Sloupce jsou "
        "<code>date &middot; club &middot; club &middot; whose-possession &middot; line &middot; over &middot; under</code> "
        "(datum, klub, klub, čí držení míče, hranice, kurz na více, kurz na méně), oddělené "
        "mezerami, s <code>-</code> pro kurz, který nemáte. Na pořadí klubů nezáleží. Použijte "
        "zkratky níže, nebo názvy bez mezer.",
}
