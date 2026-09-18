CS = {
    # -- shared admin chrome -------------------------------------------------
    "Admin": "Admin",
    "Signed in as <strong>%(user)s</strong>": "Přihlášen jako <strong>%(user)s</strong>",
    "sign out": "odhlásit",
    "advice record": "záznam doporučení",
    "import odds": "import kurzů",

    # -- admin.html ----------------------------------------------------------
    "Import odds": "Import kurzů",
    "Imported %(count)s line.": ("Importována %(count)s hranice.",
                                 "Importovány %(count)s hranice.",
                                 "Importováno %(count)s hranic."),
    "They appear on the Model and Learning pages immediately, and reach the published site on the next hourly run.":
        "Na stránkách Model a Učení se objeví hned, na zveřejněný web se dostanou "
        "při příštím hodinovém běhu.",
    "Paste rows, or upload a spreadsheet": "Vložte řádky, nebo nahrajte tabulku",
    "Paste rows here - straight from chance.cz, from a spreadsheet, or typed:":
        "Sem vložte řádky – přímo z chance.cz, z tabulky, nebo je napište:",
    "or attach a file": "nebo přiložte soubor",
    "Read it": "Načíst",
    "Pasting a selection out of a spreadsheet or the bookmaker's table works &mdash; that arrives as tab-separated text, which is read the same way a file is. <code>.xlsx</code>, <code>.csv</code> and tab-separated text are all accepted.":
        "Funguje i vložení výběru z tabulky nebo z tabulky sázkové kanceláře &mdash; "
        "dorazí jako text oddělený tabulátory a čte se stejně jako soubor. "
        "Přijímá se <code>.xlsx</code>, <code>.csv</code> i text oddělený tabulátory.",
    "With a header row, columns are matched <strong>by name</strong> rather than position &mdash; <code>Match</code> holding \"Arsenal - Chelsea\", or two separate club columns, plus date / line / over / under, in English or the Czech chance.cz uses. Reorder or insert columns freely; a positional reader would silently read the wrong field, and for odds that means recording the opposite bet.":
        "S řádkem záhlaví se sloupce párují <strong>podle názvu</strong>, ne podle pořadí "
        "&mdash; <code>Match</code> s hodnotou „Arsenal - Chelsea“, nebo dva samostatné "
        "sloupce klubů, k tomu datum / hranice / více / méně, anglicky nebo česky, jak to "
        "používá chance.cz. Sloupce můžete libovolně přehazovat i přidávat; čtení podle "
        "pořadí by potichu vzalo špatné pole, a u kurzů to znamená zapsat opačnou sázku.",
    "Without a header row, use the compact form:": "Bez řádku záhlaví použijte zkrácený tvar:",
    "date &nbsp; club &nbsp; club &nbsp; team &nbsp; line &nbsp; O&lt;over&gt; &nbsp; U&lt;under&gt;":
        "datum &nbsp; klub &nbsp; klub &nbsp; tým &nbsp; hranice &nbsp; O&lt;více&gt; &nbsp; U&lt;méně&gt;",
    "Tag the prices with O and U and their column order stops mattering.":
        "Označte kurzy písmeny O a U a na pořadí jejich sloupců přestane záležet.",
    "What this would import": "Co by se importovalo",
    "%(count)s row understood": ("%(count)s řádek rozpoznán",
                                 "%(count)s řádky rozpoznány",
                                 "%(count)s řádků rozpoznáno"),
    "%(n)s not": "%(n)s ne",
    "Match": "Zápas",
    "Line is about": "Hranice se týká",
    "Line": "Hranice",
    "Over": "Více",
    "Under": "Méně",
    "Note": "Poznámka",
    "one price": "jeden kurz",
    "margin cannot be removed": "marži nelze odečíst",
    "clubs listed the other way round": "kluby uvedeny v opačném pořadí",
    "Looks right &mdash; import these %(n)s": "Vypadá to dobře &mdash; importovat těchto %(n)s",
    "Nothing has been written yet. Re-importing the same line updates it rather than duplicating, so a correction is just another upload.":
        "Zatím se nic nezapsalo. Opětovný import stejné hranice ji aktualizuje, "
        "nevytvoří duplikát, takže oprava je prostě další nahrání.",
    "No rows could be matched to a fixture.": "Žádný řádek se nepodařilo přiřadit k zápasu.",
    "Rows that could not be used": "Řádky, které nešlo použít",
    "Recently imported": "Nedávno importováno",
    "Kickoff": "Výkop",
    "Team": "Tým",
    "Added": "Přidáno",
    "Nothing imported yet.": "Zatím nic neimportováno.",

    # -- admin_advice.html ---------------------------------------------------
    "Advice record": "Záznam doporučení",
    "What the site advised, exactly as it stood at kickoff.":
        "Co web doporučoval, přesně tak, jak to stálo ve chvíli výkopu.",
    "Each line's advice is saved on every run while its match is still to be played, and locked the moment the match kicks off &mdash; the database refuses any later change. Nothing on this page is recalculated: a new model, a new &sigma; or a code fix changes the Learning page and never this one. Only the actual possession is looked up, because that is a fact about the match.":
        "Doporučení ke každé hranici se ukládá při každém běhu, dokud se zápas nehrál, "
        "a ve chvíli výkopu se uzamkne &mdash; databáze pak žádnou změnu nepřijme. Nic na "
        "této stránce se nepřepočítává: nový model, nové &sigma; nebo oprava kódu změní "
        "stránku Učení, nikdy tuto. Dohledává se jen skutečné držení míče, protože to je "
        "fakt o zápase.",
    "The record starts on 14 Sep 2026. Bets settled before then have no saved advice, and rebuilding it would be exactly the recalculation this page exists to avoid, so they are not here.":
        "Záznam začíná 14. 9. 2026. Sázky vyhodnocené dřív nemají uložené doporučení "
        "a jeho zpětné sestavení by bylo právě tím přepočítáváním, kterému se tato "
        "stránka vyhýbá, takže tu nejsou.",
    "Bets advised, settled": "Doporučené sázky, vyhodnocené",
    "Won": "Vyhráno",
    "P/L, 1 unit each": "Zisk/ztráta, po 1 jednotce",
    "P/L at the advised stake": "Zisk/ztráta při doporučeném vkladu",
    "Beating the market by more than luck explains.":
        "Poráží trh víc, než dokáže vysvětlit náhoda.",
    "Not yet distinguishable from luck.": "Zatím nelze odlišit od náhody.",
    "%(wins)s of %(n)s won against a breakeven of %(be)s, %(z)s standard errors from it. Two is the usual bar, and at these prices it takes roughly 100&ndash;200 settled bets to reach honestly.":
        "Vyhráno %(wins)s z %(n)s při potřebné úspěšnosti %(be)s, tedy %(z)s směrodatné "
        "chyby od ní. Obvyklá laťka jsou dvě a při těchto kurzech to poctivě trvá zhruba "
        "100&ndash;200 vyhodnocených sázek.",
    "Settled": "Vyhodnocené",
    "advice frozen at kickoff": "doporučení zmrazené při výkopu",
    "League": "Liga",
    "Advised": "Doporučeno",
    "Odds": "Kurz",
    "Model": "Model",
    "Edge": "Výhoda",
    "Stake": "Vklad",
    "Actual": "Skutečnost",
    "Result": "Výsledek",
    "Last time the advice was saved before kickoff":
        "Kdy bylo doporučení naposledy uloženo před výkopem",
    "Advice as of": "Doporučení ke dni",
    "OVER": "VÍCE",
    "UNDER": "MÉNĚ",
    "no bet": "nesázet",
    "won": "výhra",
    "lost": "prohra",
    "%(count)s settled line carried no advised bet and does not count towards the totals.": (
        "%(count)s vyhodnocená hranice neměla doporučenou sázku a do součtů se nepočítá.",
        "%(count)s vyhodnocené hranice neměly doporučenou sázku a do součtů se nepočítají.",
        "%(count)s vyhodnocených hranic nemělo doporučenou sázku a do součtů se nepočítají."),
    "<sup class=\"warn\">*</sup> marks advice that came from the naive midpoint because the league could not fit a model at the time.":
        "<sup class=\"warn\">*</sup> označuje doporučení z naivního odhadu (středu), "
        "protože liga tehdy ještě neměla natrénovaný model.",
    "No advised line has settled yet. The first ones settle after the next matches with a recorded line kick off.":
        "Zatím není vyhodnocena žádná doporučená hranice. První se vyhodnotí po výkopu "
        "nejbližších zápasů se zaznamenanou hranicí.",
    "Upcoming": "Nadcházející",
    "still updating until kickoff": "aktualizuje se až do výkopu",
    "As of": "Stav k",
    "Runs happen every few hours, so what gets locked is whatever the last run before kickoff saved &mdash; the same advice the site was showing at that moment.":
        "Běhy probíhají každých pár hodin, takže se uzamkne to, co uložil poslední běh "
        "před výkopem &mdash; stejné doporučení, jaké web v tu chvíli ukazoval.",
    "No upcoming line has advice recorded yet.":
        "Žádná nadcházející hranice zatím nemá zaznamenané doporučení.",

    # -- admin_login.html ----------------------------------------------------
    "Sign in": "Přihlásit se",
    "Username": "Uživatelské jméno",
    "Password": "Heslo",
    "This page exists only in the local app. The published site is a static snapshot with no login on it.":
        "Tato stránka existuje jen v lokální aplikaci. Zveřejněný web je statický "
        "snímek bez jakéhokoli přihlášení.",

    # -- admin_setup.html ----------------------------------------------------
    "Admin not configured": "Admin není nastaven",
    "Admin is not configured": "Admin není nastaven",
    "The admin needs three values in <code>.env</code>, and refuses to run without them. That is deliberate &mdash; an admin panel with a default password is worse than one that does not work.":
        "Admin potřebuje tři hodnoty v <code>.env</code> a bez nich odmítne běžet. Je to "
        "záměr &mdash; administrace s výchozím heslem je horší než taková, která nefunguje.",
    "Generate the credentials": "Vygenerujte přihlašovací údaje",
    "Run this, then paste the three lines it prints into <code>.env</code>:":
        "Spusťte tohle a tři vypsané řádky vložte do <code>.env</code>:",
    "It asks for a username and password, hashes the password, and prints <code>ADMIN_USER</code>, <code>ADMIN_PASSWORD_HASH</code> and <code>SECRET_KEY</code>. The password itself is never stored &mdash; only a hash of it, so the file cannot give it back if someone reads it.":
        "Zeptá se na uživatelské jméno a heslo, heslo zahashuje a vypíše "
        "<code>ADMIN_USER</code>, <code>ADMIN_PASSWORD_HASH</code> a "
        "<code>SECRET_KEY</code>. Samotné heslo se nikde neukládá &mdash; jen jeho hash, "
        "takže ho soubor neprozradí, ani když ho někdo přečte.",
    "Restart <code>python app.py</code> afterwards; the values are read at startup.":
        "Poté restartujte <code>python app.py</code>; hodnoty se načítají při startu.",

    # -- app.py: errors shown on admin pages ---------------------------------
    "Too many attempts. Wait five minutes.": "Příliš mnoho pokusů. Počkejte pět minut.",
    "Wrong username or password.": "Špatné uživatelské jméno nebo heslo.",
    "Nothing staged - upload the file again.": "Nic není připraveno – nahrajte soubor znovu.",
    "Paste some rows or choose a file.": "Vložte nějaké řádky, nebo vyberte soubor.",
    "No rows understood. Include a header row naming the columns, or paste lines in the compact form: date  club  club  team  line  O<over>  U<under>":
        "Žádný řádek nebyl rozpoznán. Přidejte řádek záhlaví s názvy sloupců, nebo vložte "
        "řádky ve zkráceném tvaru: datum  klub  klub  tým  hranice  O<více>  U<méně>",

    # -- app.py: the |ago filter ---------------------------------------------
    "just now": "právě teď",
    "%(d)sd %(h)sh": "%(d)s d %(h)s h",
    "%(h)sh %(m)sm": "%(h)s h %(m)s min",
    "%(m)sm": "%(m)s min",
    "in %(t)s": "za %(t)s",
    "%(t)s ago": "před %(t)s",

    # -- app.py: match page comparison rows ----------------------------------
    "Goals": "Góly",
    "xG": "xG",
    "xG on target": "xG na branku",
    "Possession": "Držení míče",
    "Shots": "Střely",
    "On target": "Na branku",
    "Big chances": "Velké šance",
    "Corners": "Rohy",
    "Passes": "Přihrávky",
    "Accurate passes": "Přesné přihrávky",
    "Touches in opp box": "Doteky v soupeřově vápně",
    "Final third entries": "Vstupy do poslední třetiny",
    "Tackles won": "Úspěšné skluzy",
    "Interceptions": "Zachycené přihrávky",
    "Clearances": "Odkopy",
    "Saves": "Zákroky brankáře",
    "Duels won": "Vyhrané souboje",
    "Aerials won": "Vyhrané hlavičkové souboje",
    "Fouls": "Fauly",
    "Yellows": "Žluté karty",
    "Reds": "Červené karty",
    "Offsides": "Ofsajdy",

    # -- app.py: model page feature groups -----------------------------------
    "Attacking form": "Útočná forma",
    "Defensive form": "Obranná forma",
    "Points and results": "Body a výsledky",
    "Volume": "Objem",
    "Matchup edges": "Výhody ve vzájemném souboji",
    "Head to head": "Vzájemné zápasy",
    "Schedule and fatigue": "Program a únava",
    "Other": "Ostatní",

    # -- app.py: explain() - stake and verdict reasons from model.py ---------
    "no prediction available": "předpověď není k dispozici",
    "no price recorded": "není zaznamenán kurz",
    "no price": "bez kurzu",
    "no edge - the price is against you": "bez výhody – kurz je proti vám",
    "best side is %(side)s at %(odds)s, still %(gap)s short of its %(be)s breakeven":
        "lepší strana je %(side)s za %(odds)s, stále o %(gap)s pod potřebnou "
        "úspěšností %(be)s",
    "edge alone suggests %(score)s/10, capped at %(cap)s %(by)s (%(n)s settled)":
        "samotná výhoda by dala %(score)s/10, omezeno na %(cap)s %(by)s "
        "(%(n)s vyhodnocených)",
    "by almost no track record": "kvůli téměř žádné historii výsledků",
    "by a very thin track record": "kvůli velmi krátké historii výsledků",
    "by a thin track record": "kvůli krátké historii výsledků",
    "by a short track record": "kvůli zatím omezené historii výsledků",
    "by a moderate track record": "kvůli středně dlouhé historii výsledků",
    "by a substantial track record": "kvůli dlouhé historii výsledků",
    "edge of %(edge)s at %(odds)s": "výhoda %(edge)s při kurzu %(odds)s",
    "no settled bets yet - nothing has been tested":
        "zatím žádné vyhodnocené sázky – nic nebylo otestováno",
    "only %(num)s settled bet. Below about 50 the result is noise whichever way it falls": (
        "jen %(num)s vyhodnocená sázka. Pod zhruba 50 je výsledek šum, ať dopadne jakkoli",
        "jen %(num)s vyhodnocené sázky. Pod zhruba 50 je výsledek šum, ať dopadne jakkoli",
        "jen %(num)s vyhodnocených sázek. Pod zhruba 50 je výsledek šum, ať dopadne jakkoli"),
    "%(w)s/%(n)s at %(rate)s against a %(be)s breakeven - %(z)s standard errors clear, which luck does not explain":
        "%(w)s/%(n)s, úspěšnost %(rate)s proti potřebným %(be)s – o %(z)s směrodatné "
        "chyby výš, což náhoda nevysvětlí",
    "%(w)s/%(n)s at %(rate)s, below the %(be)s breakeven - the model is losing to the price":
        "%(w)s/%(n)s, úspěšnost %(rate)s, pod potřebnými %(be)s – model s kurzem prohrává",
    "%(w)s/%(n)s at %(rate)s against %(be)s breakeven, but only %(z)s standard errors clear; about %(k)s settled bets at this rate would settle it":
        "%(w)s/%(n)s, úspěšnost %(rate)s proti potřebným %(be)s, ale jen o %(z)s "
        "směrodatné chyby výš; při tomto tempu by to rozhodlo zhruba %(k)s "
        "vyhodnocených sázek",
    "%(w)s/%(n)s at %(rate)s against %(be)s breakeven, but only %(z)s standard errors clear":
        "%(w)s/%(n)s, úspěšnost %(rate)s proti potřebným %(be)s, ale jen o %(z)s "
        "směrodatné chyby výš",
    "ROI, 1 unit each": "ROI, 1 jednotka na sázku",
    "at the advised stake": "při doporučeném vkladu",
}
