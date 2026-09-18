CS = {
    # -- model.html: all leagues -------------------------------------------
    "<strong>Every league's open lines in one place.</strong> The panels below this one are missing on purpose: a training set, a feature inventory and an error baseline each describe <em>one</em> league's own data, and stacking three leagues' rows into them would describe a model that does not exist. Pick a league above for those. What genuinely spans leagues is the guidance, and which leagues are modelled at all.":
        "<strong>Otevřené hranice všech lig na jednom místě.</strong> Panely, které jsou jinak pod tímto, tu záměrně chybí: trénovací sada, přehled příznaků i základní chyba vždy popisují data <em>jedné</em> ligy a slepením řádků tří lig by vznikl popis modelu, který neexistuje. Pro ně vyberte ligu nahoře. Napříč ligami má smysl jen doporučení k vkladu a to, které ligy se vůbec modelují.",
    "Modelling readiness": "Připravenost modelu",
    "which leagues have enough history to fit": "které ligy mají dost historie na natrénování",
    "League": "Liga",
    "Training rows": "Trénovací řádky",
    "Needed": "Potřeba",
    "Predictions from": "Předpovědi z",
    "Mean absolute error, walk-forward": "Průměrná absolutní chyba, průběžný test (walk-forward)",
    "Error": "Chyba",
    "The naive midpoint's error on the same matches": "Chyba naivního odhadu na stejných zápasech",
    "Naive": "Naivní",
    "Spread of the errors - how wide the probability curve is": "Rozptyl chyb - jak široká je křivka pravděpodobnosti",
    "Share of errors inside 1 / 1.645 / 1.96 sigma. A normal curve gives 68 / 90 / 95.":
        "Podíl chyb uvnitř 1 / 1.645 / 1.96 sigma. Normální rozdělení dává 68 / 90 / 95.",
    "Calibration": "Kalibrace",
    "Lines": "Hranice",
    "Settled": "Vyhodnocené",
    "fitted model": "natrénovaný model",
    "naive midpoint": "naivní odhad",
    "not measured &mdash; &sigma; %(s)s assumed": "neměřeno &mdash; předpokládá se &sigma; %(s)s",
    "Error and &sigma; are measured walk-forward over every match the fit could have predicted &mdash; refit before each, never shown its own future &mdash; and refreshed before every site rebuild. Each league's stake guidance uses its own &sigma;: a wider spread means the same gap to a line is worth less. A league under %(n)s rows falls back to the naive midpoint &mdash; the side's own recent possession averaged against what its opponent concedes. Those rows are marked <sup class=\"warn\">*</sup> below. The threshold is about four rows per feature, a rule of thumb rather than a measured cliff.":
        "Chyba a &sigma; se měří průběžným testem (walk-forward) na každém zápase, který model mohl předpovědět &mdash; před každým se znovu natrénuje a nikdy nevidí vlastní budoucnost &mdash; a přepočítávají se před každým přegenerováním webu. Doporučení k vkladu používá v každé lize její vlastní &sigma;: širší rozptyl znamená, že stejný odstup od hranice má menší cenu. Liga s méně než %(n)s řádky se vrací k naivnímu odhadu &mdash; nedávné držení míče týmu zprůměrované s tím, kolik míče soupeř obvykle přenechává. Takové řádky jsou níže označené <sup class=\"warn\">*</sup>. Hranice je zhruba čtyři řádky na příznak, spíš orientační pravidlo než změřený zlom.",

    # -- model.html: one league --------------------------------------------
    "<strong>Target: home possession %%.</strong> Possession is zero-sum inside a match, so this one number defines the whole result &mdash; the away side is 100 minus it. This is a regression problem, not a win/draw/lose one. <strong>No model is trained yet;</strong> the figures below are what the modelling layer has to work with.":
        "<strong>Cíl: držení míče domácích (%%).</strong> Držení míče je v zápase hra s nulovým součtem, takže tohle jediné číslo určuje celý výsledek &mdash; hosté mají 100 minus ono. Jde o regresi, ne o tip výhra/remíza/prohra. <strong>Zatím není natrénovaný žádný model;</strong> čísla níže ukazují, s čím modelovací vrstva může pracovat.",
    "Usable features": "Použitelné příznaky",
    "Fit split": "Trénovací část",
    "Holdout split": "Testovací část",
    "Fixtures to score": "Zápasy k předpovědi",
    "What a model must beat": "Co musí model překonat",
    "mean absolute error, percentage points": "průměrná absolutní chyba, procentní body",
    "Always predict 50%%": "Vždy tipovat 50 %%",
    "The know-nothing floor": "Úroveň „nic nevím“",
    "Home side's own recent average": "Nedávný průměr domácích",
    "Ignores who they are playing": "Nebere ohled na soupeře",
    "Naive midpoint": "Naivní odhad",
    "Home form vs what the away side concedes &mdash; the one that matters":
        "Forma domácích proti tomu, co hosté přenechávají &mdash; ten podstatný",
    "A model is only earning its keep below <strong>%(x)s</strong> points of error. Beating \"always 50\" is not an achievement.":
        "Model má smysl teprve pod chybou <strong>%(x)s</strong> bodu. Porazit „vždy 50“ není žádný úspěch.",
    "Not enough data yet.": "Zatím málo dat.",
    "Training set": "Trénovací sada",
    "Rows": "Řádky",
    "Played matches where both sides had enough prior matches to form an average":
        "Odehrané zápasy, kde oba týmy měly dost předchozích zápasů na průměr",
    "Home possession seen": "Rozsah držení míče domácích",
    "Mean / spread": "Průměr / rozptyl",
    "Earliest match": "Nejstarší zápas",
    "Latest match": "Nejnovější zápas",
    "Split": "Rozdělení",
    "Chronological, never random": "Chronologicky, nikdy náhodně",
    "No training rows for this league yet.": "Tato liga zatím nemá žádné trénovací řádky.",
    "%(count)s match played, and <code>min_history</code> is %(mh)s &mdash; every row needs both sides to have %(mh)s earlier matches to average, which nobody has until about matchday %(md)s.": (
        "Odehrán %(count)s zápas a <code>min_history</code> je %(mh)s &mdash; každý řádek potřebuje, aby oba týmy měly %(mh)s předchozích zápasů na průměr, a to nikdo nemá zhruba do %(md)s. kola.",
        "Odehrány %(count)s zápasy a <code>min_history</code> je %(mh)s &mdash; každý řádek potřebuje, aby oba týmy měly %(mh)s předchozích zápasů na průměr, a to nikdo nemá zhruba do %(md)s. kola.",
        "Odehráno %(count)s zápasů a <code>min_history</code> je %(mh)s &mdash; každý řádek potřebuje, aby oba týmy měly %(mh)s předchozích zápasů na průměr, a to nikdo nemá zhruba do %(md)s. kola.",
    ),
    "Nothing is broken; the season is young. The figures below are what the model <em>will</em> use once there is something to fit.":
        "Nic není rozbité, sezóna je prostě mladá. Čísla níže ukazují, co model <em>bude</em> používat, až bude na čem trénovat.",
    "<strong>%(nf)s features against %(nt)s rows.</strong> More columns than examples means any model will fit the training data perfectly and learn nothing that generalises. Until the season fills out, prefer a handful of possession columns and strong regularisation over the full set &mdash; or widen <code>training.season</code> in config.yaml.":
        "<strong>%(nf)s příznaků proti %(nt)s řádkům.</strong> Víc sloupců než příkladů znamená, že každý model trénovací data dokonale napasuje a nenaučí se nic obecně platného. Dokud se sezóna nenaplní, dejte přednost několika sloupcům držení míče a silné regularizaci před celou sadou &mdash; nebo rozšiřte <code>training.season</code> v config.yaml.",
    "Thin features": "Řídké příznaky",
    "present in fewer than half the training rows": "vyplněné v méně než polovině trénovacích řádků",
    "Mostly head-to-head columns: within one season two clubs have met at most once by now, so there is usually no prior meeting to average. These fill in from January, when the reverse fixtures start.":
        "Většinou sloupce vzájemných zápasů: během jedné sezóny se dva kluby zatím potkaly nejvýš jednou, takže obvykle není z čeho průměrovat. Doplní se od ledna, kdy začnou odvety.",
    "Feature inventory": "Přehled příznaků",
    "%(n)s columns the model would use, taken from the fixture side since there is no training set yet":
        "%(n)s sloupců, které by model použil, převzatých z nadcházejících zápasů, protože trénovací sada zatím neexistuje",
    "%(n)s columns present in both training and fixtures":
        "%(n)s sloupců přítomných v trénovací sadě i v nadcházejících zápasech",
    "Minutes spent ahead, level and behind are deliberately <em>not</em> here. They are only known after the whistle, so using them to predict possession would be leakage. They are stored for explaining errors instead: a match settled early is inherently less predictable, because the leading side stops trying to keep the ball.":
        "Minuty ve vedení, za stavu nerozhodně a v manku tu záměrně <em>nejsou</em>. Známe je až po závěrečném hvizdu, takže použít je k předpovědi držení míče by byl únik informací. Ukládají se místo toho k vysvětlování chyb: zápas rozhodnutý brzy je z podstaty hůř předvídatelný, protože vedoucí tým přestane usilovat o míč.",
    # feature group names (dict keys in app.py, translated at display time)
    "Possession": "Držení míče",
    "Attacking form": "Útočná forma",
    "Defensive form": "Obranná forma",
    "Points and results": "Body a výsledky",
    "Volume": "Objem",
    "Matchup edges": "Výhody ve vzájemném souboji",
    "Head to head": "Vzájemné zápasy",
    "Schedule and fatigue": "Program a únava",
    "Other": "Ostatní",

    # -- model.html: stake guidance ----------------------------------------
    "Stake guidance": "Doporučení k vkladu",
    "open lines, rated out of 10": "otevřené hranice, hodnocení z 10",
    "Two separate things have to be true before staking much: the edge must be large, <em>and</em> the model must have shown it can find real edges. The first is arithmetic; the second is a track record. The rating is the smaller of the two, so a big edge from a model with no record scores low &mdash; correctly.":
        "Než vsadíte víc, musí platit dvě samostatné věci: výhoda musí být velká <em>a</em> model musí mít prokázáno, že skutečné výhody umí najít. To první je aritmetika, to druhé výsledková historie. Hodnocení je menší z obou, takže velká výhoda od modelu bez historie dostane nízké číslo &mdash; a správně.",
    "It is <strong>%(count)s</strong> settled bet in, so the ceiling is low for a while yet.": (
        "Zatím je vyhodnocená <strong>%(count)s</strong> sázka, takže strop ještě nějakou dobu zůstane nízko.",
        "Zatím jsou vyhodnocené <strong>%(count)s</strong> sázky, takže strop ještě nějakou dobu zůstane nízko.",
        "Zatím je vyhodnoceno <strong>%(count)s</strong> sázek, takže strop ještě nějakou dobu zůstane nízko.",
    ),
    "Kickoff": "Výkop",
    "Match": "Zápas",
    "Line is about": "Hranice se týká",
    "Line": "Hranice",
    "Under": "Méně",
    "Over": "Více",
    "Model": "Model",
    "Market": "Trh",
    "Bet": "Sázka",
    "Edge": "Výhoda",
    "Stake": "Vklad",
    "Why": "Proč",
    "No fitted model for this league yet - naive midpoint":
        "Pro tuto ligu zatím není natrénovaný model - naivní odhad (střed)",
    "bookmaker's own probability, margin removed": "pravděpodobnost sázkové kanceláře bez marže",
    "%(p)s over": "%(p)s více",
    "OVER": "VÍCE",
    "UNDER": "MÉNĚ",
    "no bet": "nesázet",
    "<strong>%(count)s row here did not come from a fitted model.</strong>": (
        "<strong>%(count)s řádek zde nepochází z natrénovaného modelu.</strong>",
        "<strong>%(count)s řádky zde nepochází z natrénovaného modelu.</strong>",
        "<strong>%(count)s řádků zde nepochází z natrénovaného modelu.</strong>",
    ),
    "This league has too little history to fit one, so the figure is the naive midpoint: the side's own recent possession averaged against what its opponent concedes &mdash; on as few as two matches each. That formula shrinks towards 50 by construction, so it understates a mismatch. A strong side away at a weak one reads too low, and the edge it implies against a bookmaker's line can point the wrong way entirely. The Bet, Edge and Stake columns on these rows are arithmetic, not a tested prediction.":
        "Tato liga má na natrénování modelu příliš krátkou historii, takže číslo je naivní odhad: nedávné držení míče týmu zprůměrované s tím, kolik míče soupeř přenechává &mdash; klidně jen ze dvou zápasů každého z nich. Tento vzorec z principu táhne k 50, takže nerovný souboj podhodnocuje. Silný tým venku u slabého vychází příliš nízko a výhoda, kterou to naznačuje proti hranici sázkové kanceláře, může ukazovat úplně opačným směrem. Sloupce Sázka, Výhoda a Vklad jsou u těchto řádků jen aritmetika, ne ověřená předpověď.",
    "<strong>0/10</strong> means the price is against you &mdash; not a close call, a bet to skip. Anything above that is a fraction of what you would stake at full confidence, and quarter-Kelly is treated as the ceiling even at 10/10, because Kelly assumes the probability is exactly right and this one is an estimate.":
        "<strong>0/10</strong> znamená, že kurz je proti vám &mdash; nejde o těsné rozhodnutí, sázku vynechte. Cokoli vyšší je zlomek vkladu, který byste dali při plné jistotě, a i při 10/10 je stropem čtvrtinový Kelly, protože Kelly předpokládá přesně správnou pravděpodobnost, kdežto tahle je jen odhad.",
    "No open lines recorded. Add them to <code>odds.txt</code> and they appear here.":
        "Nejsou zaznamenané žádné otevřené hranice. Přidejte je do <code>odds.txt</code> a objeví se tady.",
    "Next fixtures": "Nejbližší zápasy",
    "with the naive prediction to beat": "s naivní předpovědí, kterou je třeba překonat",
    "Home form": "Forma domácích",
    "Away form": "Forma hostů",
    "Gap": "Rozdíl",
    "Naive home poss": "Naivní držení domácích",
    "No fixtures stored.": "Nejsou uložené žádné zápasy.",

    # -- fixtures.html -----------------------------------------------------
    "Upcoming fixtures": "Nadcházející zápasy",
    "<strong>The next %(horizon)s days across all three leagues.</strong> This view is horizon-limited where the per-league tabs are not: Bundesliga and LaLiga each store a whole season of fixtures &mdash; 281 and 332 against the Premier League's 21 &mdash; so showing everything here would be 634 rows of mostly May. Pick a league above for its full list.":
        "<strong>Příštích %(horizon)s dní ve všech třech ligách.</strong> Tento pohled je časově omezený, karty jednotlivých lig ne: Bundesliga i LaLiga mají uložený program celé sezóny &mdash; 281 a 332 zápasů proti 21 v Premier League &mdash; takže zobrazit tu všechno by znamenalo 634 řádků převážně z května. Celý seznam najdete po výběru ligy nahoře.",
    "<strong>%(w)s of %(count)s fixtures have a line recorded.</strong>": (
        "<strong>Hranici má zaznamenanou %(w)s z %(count)s zápasu.</strong>",
        "<strong>Hranici má zaznamenanou %(w)s z %(count)s zápasů.</strong>",
        "<strong>Hranici má zaznamenanou %(w)s z %(count)s zápasů.</strong>",
    ),
    "Where one does, the bet column shows which side the model prefers and how much of a stake that is worth &mdash; capped by track record, which is %(count)s settled bet so far.": (
        "Kde ji má, ukazuje sloupec sázky, kterou stranu model preferuje a jak velký vklad si zaslouží &mdash; omezeno výsledkovou historií, což je zatím %(count)s vyhodnocená sázka.",
        "Kde ji má, ukazuje sloupec sázky, kterou stranu model preferuje a jak velký vklad si zaslouží &mdash; omezeno výsledkovou historií, což jsou zatím %(count)s vyhodnocené sázky.",
        "Kde ji má, ukazuje sloupec sázky, kterou stranu model preferuje a jak velký vklad si zaslouží &mdash; omezeno výsledkovou historií, což je zatím %(count)s vyhodnocených sázek.",
    ),
    "<strong>No lines recorded for these fixtures yet.</strong> Add them through the admin and the bet column fills in.":
        "<strong>K těmto zápasům zatím nejsou zaznamenané žádné hranice.</strong> Přidejte je v Adminu a sloupec sázky se vyplní.",
    "These are the prediction targets, with the same pre-kickoff features the model will see &mdash; from <strong>v_fixture_features</strong>. Nothing here uses information from after the whistle. <strong>xGD edge</strong> is the home side's L5 xG difference minus the away side's: positive favours the home team.":
        "Tohle jsou zápasy k předpovědi se stejnými předzápasovými příznaky, jaké uvidí model &mdash; z <strong>v_fixture_features</strong>. Nic tu nepoužívá informace z doby po závěrečném hvizdu. <strong>Výhoda xGD</strong> je rozdíl xG domácích za posledních 5 zápasů minus totéž u hostů: kladné číslo nahrává domácím.",
    "MW": "Kolo",
    "Home": "Domácí",
    "Away": "Hosté",
    "xGD edge": "Výhoda xGD",
    "PPG edge": "Výhoda PPG",
    "H att v A def": "Útok D v obr. H",
    "A att v H def": "Útok H v obr. D",
    "H rest": "Odpočinek D",
    "A rest": "Odpočinek H",
    "H2H": "Vzáj.",
    "Hist": "Hist.",
    "Bet available": "Možná sázka",
    "Matches of history behind each side's form": "Počet zápasů historie za formou každého týmu (D/H)",
    "price is against you": "kurz je proti vám",
    "No upcoming fixtures stored. Run the scraper.": "Nejsou uložené žádné nadcházející zápasy. Spusťte stahování.",
}
