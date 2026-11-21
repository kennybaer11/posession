"""Czech for the basketball pages (basketball.html, basketball_lines.html)."""
CS = {
    "Basketball": "Basketbal",
    "Basketball tips": "Tipy na basketbal",
    "Basketball results": "Výsledky tipů na basketbal",
    "Basketball: all lines": "Basketbal: všechny hranice",
    "Total points": "Celkem bodů",
    "Team points": "Body týmu",
    "1st half": "1. poločas",
    "full game": "celý zápas",
    "Whole game": "Celý zápas",
    "Whole game and halves": "Zápas i poločasy",
    "All leagues": "Všechny ligy",
    "Centre": "Střed",
    "Expected": "Očekávání",
    "model": "model",
    "Where the expected points come from": "Odkud je očekávaný počet bodů",
    "No priced basketball line right now.": "Teď není oceněná žádná basketbalová hranice.",
    "No basketball line has settled yet.": "Zatím se nevyhodnotila žádná basketbalová hranice.",
    "Settled +6% lines": "Vyhodnocené hranice s výhodou +6 %",
    "Not paired with a game in the results feed yet.": "Zatím nespárováno se zápasem ve výsledcích.",
    "landed exactly on a whole-number line, or no result in the data; not counted":
        "skončilo přesně na celočíselné hranici, nebo chybí výsledek; nepočítá se",
    "Lines the model rated +6%% or better: %(n)s settled, %(won)s won, %(pnl)s units at a flat unit (%(roi)s).":
        "Hranice, kterým model dal výhodu +6 %% a víc: vyhodnoceno %(n)s, vyhráno %(won)s, "
        "%(pnl)s jednotek při stejném vkladu (%(roi)s).",
    "The basketball tips started on 21 Nov 2026. They do not try to out-guess the American market: the expected points come from DraftKings' line, and a tip is a Betano line that disagrees with it - most often a first-half line out of step with Betano's own full-game total. That gap is real in the data (NBA first halves score 50.5%% of the points; on the first day Betano's first-half lines ran from 48%% to 52%% of its own total), but whether Betano's prices leave enough of it after the margin is what this record will show. Small stakes until it does.":
        "Tipy na basketbal začaly 21. 11. 2026. Nesnaží se přechytračit americký trh: očekávaný počet "
        "bodů je z hranice DraftKings a tip je hranice Betana, která s ní nesouhlasí – nejčastěji "
        "poločasová hranice, která nesedí k vlastnímu celkovému součtu Betana. Ten rozdíl v datech je "
        "(v NBA padá v prvním poločase 50,5 %% bodů; první den byly poločasové hranice Betana od 48 do "
        "52 %% jeho vlastního součtu), ale jestli po marži Betana z něj něco zbude, ukáže až tento "
        "záznam. Do té doby malé vklady.",
    "Each tip is saved every time Betano's lines are collected and priced, and locked the moment its game starts &mdash; the database refuses any later change. Nothing here is recalculated; only the score is looked up. Tips are over/under lines on points - both teams' total, or one team's - for the whole game (overtime included, as Betano settles them) or the first half, at +6%% value or more on the model's chance blended 3:1 with Betano's own (margin taken out), at most one per game and half.":
        "Každý tip se uloží pokaždé, když se stáhnou a ocení hranice Betana, a zamkne se ve chvíli, "
        "kdy zápas začne &mdash; databáze pak jakoukoli změnu odmítne. Nic se tu nepřepočítává, jen se "
        "dohledá skóre. Tipy jsou hranice více/méně na body – součet obou týmů, nebo jednoho týmu – na "
        "celý zápas (včetně prodloužení, jak je Betano vyhodnocuje) nebo na první poločas, s výhodou "
        "+6 %% a víc na šanci modelu smíchané 3:1 se šancí Betana (bez marže), nejvýš jeden na zápas a poločas.",
    "<strong>How a line is priced.</strong> The expected points are DraftKings' line for the game (its total, split between the teams by its spread; a first half by the share of the points first halves score). Around it, a spread measured on three seasons of results against the closing line: in the NBA the total lands within 18 points of the close two times in three. A team-rating model is kept alongside but barely moves the centre - on past NBA seasons it added nothing to the closing line.":
        "<strong>Jak se hranice oceňuje.</strong> Očekávaný počet bodů je hranice DraftKings na zápas "
        "(její součet, rozdělený mezi týmy podle handicapu; první poločas podle podílu bodů, které v "
        "prvních poločasech padají). Kolem ní rozptyl změřený na třech sezonách výsledků proti "
        "závěrečné hranici: v NBA skončí součet do 18 bodů od ní ve dvou zápasech ze tří. Model "
        "hodnocení týmů běží vedle, ale střed skoro neposouvá – na minulých sezonách NBA k závěrečné "
        "hranici nic nepřidal.",
    "<strong>Stake</strong> is in tenths of a unit: 10/10 is a full unit, whatever size you choose for one. It is quarter Kelly on the model's chance blended half and half with the bookmaker's, lower for long odds, and tips on the same game share one stake.":
        "<strong>Vklad</strong> je v desetinách jednotky: 10/10 je celá jednotka, ať si ji zvolíte "
        "jakkoli velkou. Je to čtvrtinový Kelly na šanci modelu smíchanou napůl se šancí sázkové "
        "kanceláře, nižší u vysokých kurzů, a tipy na stejný zápas sdílejí jeden vklad.",
    "Results and lines: ESPN; EuroLeague and EuroCup from the EuroLeague's own data.":
        "Výsledky a hranice: ESPN; Euroliga a EuroCup z vlastních dat Euroligy.",
    "These are the model's prices, not tips. Where the expected points come from DraftKings (NBA, NCAA, WNBA), an edge means Betano's line is out of step with the American market; where they come from Betano itself (EuroLeague, EuroCup), only the spread around Betano's own centre is the model's, and those lines are never tipped. The settled lines below show which of the two is worth anything.":
        "Toto jsou ceny modelu, ne tipy. Kde je očekávaný počet bodů z DraftKings (NBA, NCAA, WNBA), "
        "výhoda znamená, že hranice Betana nesedí k americkému trhu; kde je z Betana samotného "
        "(Euroliga, EuroCup), je od modelu jen rozptyl kolem středu Betana a tyto hranice se nikdy "
        "netipují. Vyhodnocené hranice níže ukážou, co z toho má cenu.",
    "%(n)s lines, the best-priced on each side": "%(n)s hranic, na každé straně ta nejlépe oceněná",
}
