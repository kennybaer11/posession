"""Read possession lines out of a spreadsheet.

Accepts .xlsx / .xlsm (openpyxl) and .csv / .tsv / .txt, and produces the same
row shape `import_odds.parse` does, so everything downstream is shared.

Columns are found BY HEADER, not by position. A spreadsheet gets reordered,
gets a column inserted, gets exported in Czech - and a positional reader
silently reads the wrong field, which for odds means recording the opposite
bet. Matching on the header name fails loudly instead, and accepts both
languages because that is what the source site produces.
"""

import csv
import io
import re
from datetime import date, datetime

# header text (lowercased, stripped) -> field. Czech first, since that is what
# chance.cz exports; English alternatives for a hand-built sheet.
HEADERS = {
    "date": ("day", "date", "den", "datum", "datum zápasu"),
    "match": ("match", "zápas", "zapas", "utkání", "utkani"),
    "bet": ("bet", "sázka", "sazka", "trh", "market"),
    # Whose possession the line is about.
    "team": ("team", "tým", "tym", "whose", "side"),
    # The two clubs, when they are in separate columns rather than one "Match"
    # cell. A sheet may label them home/away, or simply repeat "club" twice -
    # which is what the text format documents, so it is what people build.
    "club": ("club", "klub", "home", "away", "domácí", "domaci", "hosté", "hoste"),
    "line": ("line", "hranice", "limit", "čára", "cara"),
    "under": ("under", "méně", "mene", "under odd", "kurz méně", "kurz mene"),
    "over": ("over", "více", "vice", "over odd", "kurz více", "kurz vice"),
}


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _num(value):
    """Accept 1,94 and 1.94, and pull a number out of '54,5 a více'."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(m.group(0).replace(",", ".")) if m else None


def _date(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    return m.group(0) if m else text


def _map_headers(row):
    """Which columns might hold which field. Returns {field: [indices]}.

    Lists, not single indices, because chance.cz gives each side TWO columns:
    "Mene" holds the line as prose ("Mene nez 55,5") and "Under odd" holds the
    price. Both legitimately answer to "under", so the header cannot settle it
    alone - taking the first match silently loses every price. Which is which
    is decided from the data in _pick_price.
    """
    found = {}
    for i, cell in enumerate(row):
        name = _norm(cell)
        if not name:
            continue
        for field, aliases in HEADERS.items():
            if any(name == a or name.startswith(a) for a in aliases):
                found.setdefault(field, []).append(i)
                break
    return found


_TAGGED = re.compile(r"(?i)^\s*([ou])[:=]?\s*(\d+(?:[.,]\d+)?)\s*$")


def _is_bare_number(value):
    """Is this cell a price rather than prose?

    A price is a number, optionally tagged O1.84 / U1.94 the way the text
    format allows. A line arrives wrapped in words ("Mene nez 54,5").
    """
    if isinstance(value, (int, float)):
        return True
    if value is None:
        return False
    text = str(value).strip()
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?", text) or _TAGGED.match(text))


def _tagged_price(value):
    """(side, price) for a tagged cell, else (None, price-or-None)."""
    if isinstance(value, (int, float)):
        return None, float(value)
    m = _TAGGED.match(str(value or ""))
    if m:
        return m.group(1).lower(), float(m.group(2).replace(",", "."))
    text = str(value or "").strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return None, float(text.replace(",", "."))
    return None, None


def _pick_price(grid, header_at, candidates):
    """Of several candidate columns for one side, which holds the odds.

    Decided by looking at the values rather than the header: the price column
    is bare numbers, the line column is text with a number buried in it. A
    header-only guess picks wrong on chance.cz's own export, and picking wrong
    means no price at all rather than an obvious error.
    """
    for i in candidates:
        values = [row[i] for row in grid[header_at + 1:header_at + 8]
                  if i < len(row) and row[i] not in (None, "")]
        if values and all(_is_bare_number(v) for v in values):
            return i
    return None


def _pick_line_source(grid, header_at, candidates, price_index):
    """The column carrying the line - whichever candidate is not the price."""
    for i in candidates:
        if i != price_index:
            return i
    return None


def _split_match(text):
    """'Arsenal - Chelsea' -> ('Arsenal', 'Chelsea')."""
    for sep in (" - ", " – ", " vs ", " v "):
        if sep in text:
            a, b = text.split(sep, 1)
            return a.strip(), b.strip()
    return None, None


def _team_from_bet(text, fallback):
    """Pull the club out of 'Procento drzeni mice Arsenal v zapasu'."""
    if not text:
        return fallback
    s = re.sub(r"(?i)^.*?(?:m[ií][cč]e|possession)\s+", "", str(text))
    s = re.sub(r"(?i)\s+v\s+z[aá]pas.*$", "", s).strip()
    return s or fallback


def _rows_from_grid(grid):
    """Turn a list-of-lists into parsed line dicts."""
    header_at, columns = None, {}
    for i, row in enumerate(grid[:10]):
        found = _map_headers(row)
        # A usable header row identifies a date plus some way of naming the
        # fixture - either one "Match" cell or two club columns.
        if "date" in found and (found.get("match") or len(found.get("club", [])) >= 2):
            header_at, columns = i, found
            break
    if header_at is None:
        raise ValueError(
            "No usable header row found in the first 10 rows. The sheet needs "
            "a date column plus either a 'Match' column holding "
            "'Arsenal - Chelsea', or two club columns (home and away).")

    under_cols = columns.get("under", [])
    over_cols = columns.get("over", [])
    under_price = _pick_price(grid, header_at, under_cols)
    over_price = _pick_price(grid, header_at, over_cols)
    under_text = _pick_line_source(grid, header_at, under_cols, under_price)
    over_text = _pick_line_source(grid, header_at, over_cols, over_price)
    line_col = (columns.get("line") or [None])[0]
    match_col = (columns.get("match") or [None])[0]
    club_cols = columns.get("club", [])
    team_col = (columns.get("team") or [None])[0]
    bet_col = (columns.get("bet") or [None])[0]

    def at(row, i):
        return row[i] if i is not None and i < len(row) else None

    out = []
    for n, row in enumerate(grid[header_at + 1:], start=header_at + 2):
        raw_date = at(row, (columns.get("date") or [None])[0])
        if raw_date in (None, ""):
            continue

        home = away = None
        if match_col is not None and at(row, match_col):
            home, away = _split_match(str(at(row, match_col)))
        elif len(club_cols) >= 2:
            home, away = at(row, club_cols[0]), at(row, club_cols[1])
        if not (home and away):
            continue

        team = at(row, team_col) if team_col is not None else None
        if not team:
            team = _team_from_bet(at(row, bet_col), home)

        line = _num(at(row, line_col))
        if line is None:
            line = _num(at(row, under_text))
        if line is None:
            line = _num(at(row, over_text))
        if line is None:
            continue

        # Read the prices, letting an O/U tag override which column they sat
        # in. A tagged cell says what it is, and that beats its position.
        over = under = None
        for idx in (over_price, under_price, over_text, under_text):
            if idx is None:
                continue
            side, price = _tagged_price(at(row, idx))
            if price is None:
                continue
            if side == "o":
                over = price
            elif side == "u":
                under = price
            elif idx == over_price:
                over = price
            elif idx == under_price:
                under = price

        out.append({
            "n": n,
            "date": _date(raw_date),
            "home": str(home).strip().replace(" ", ""),
            "away": str(away).strip().replace(" ", ""),
            "team": str(team).strip().replace(" ", ""),
            "line": line,
            "over": over,
            "under": under,
        })
    return out


def parse_bytes(data, filename=""):
    """Parse an uploaded file. Returns the same rows import_odds.parse does."""
    name = (filename or "").lower()

    if name.endswith((".xlsx", ".xlsm", ".xltx")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        grid = [[c for c in row] for row in wb.active.iter_rows(values_only=True)]
        return _rows_from_grid(grid)

    if name.endswith(".xls"):
        raise ValueError(
            "Old .xls files are not supported - open it in Excel and save as "
            ".xlsx, or export as CSV.")

    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    grid = [row for row in csv.reader(io.StringIO(text), dialect)]
    return _rows_from_grid(grid)
