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
    "team": ("team", "tým", "tym", "klub", "club"),
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


def _is_bare_number(value):
    """A price is a number and nothing else; a line arrives wrapped in prose."""
    if isinstance(value, (int, float)):
        return True
    if value is None:
        return False
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?", str(value).strip()))


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
    header_at = None
    columns = {}
    for i, row in enumerate(grid[:10]):
        found = _map_headers(row)
        # A usable header row identifies at least a date and a line/match.
        if "date" in found and ("line" in found or "match" in found):
            header_at, columns = i, found
            break
    if header_at is None:
        raise ValueError(
            "No header row found. The sheet needs column titles - Day/Match/"
            "Bet/Under/Over, or Czech equivalents - somewhere in the first "
            "10 rows.")

    # Resolve the two-columns-per-side ambiguity from the data.
    under_cols = columns.get("under", [])
    over_cols = columns.get("over", [])
    under_price = _pick_price(grid, header_at, under_cols)
    over_price = _pick_price(grid, header_at, over_cols)
    under_text = _pick_line_source(grid, header_at, under_cols, under_price)
    over_text = _pick_line_source(grid, header_at, over_cols, over_price)
    line_col = (columns.get("line") or [None])[0]

    def at(row, i):
        return row[i] if i is not None and i < len(row) else None

    out = []
    for n, row in enumerate(grid[header_at + 1:], start=header_at + 2):
        raw_date = at(row, (columns.get("date") or [None])[0])
        if raw_date in (None, ""):
            continue

        home = away = None
        match_cell = at(row, (columns.get("match") or [None])[0])
        if match_cell:
            home, away = _split_match(str(match_cell))
        if not (home and away):
            continue

        team = _team_from_bet(at(row, (columns.get("bet") or [None])[0]), home)
        if columns.get("team"):
            team = at(row, columns["team"][0]) or team

        # The line may have its own column, or be embedded in the prose of
        # either side ("Mene nez 54,5" / "54,5 a vice").
        line = _num(at(row, line_col))
        if line is None:
            line = _num(at(row, under_text))
        if line is None:
            line = _num(at(row, over_text))
        if line is None:
            continue

        out.append({
            "n": n,
            "date": _date(raw_date),
            "home": str(home).replace(" ", ""),
            "away": str(away).replace(" ", ""),
            "team": str(team).replace(" ", ""),
            "line": line,
            "over": _num(at(row, over_price)),
            "under": _num(at(row, under_price)),
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
