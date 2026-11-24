"""Team contract helpers (pure pandas, no Docling needed).

Contract format shared by all 4 members:
{
  "doc_id": "report1", "table_id": "report1_p3_t1", "page": 3,
  "columns": ["Item", "Q1", "Q2", "Total"],
  "rows": [["A", 10, 20, 30], ["B", 5, 5, 10], ["Total", 15, 25, 40]]
}
Empty cells are null (None) so the harness can detect them.
"""
from __future__ import annotations

import re

import pandas as pd

REQUIRED_KEYS = {"doc_id", "table_id", "page", "columns", "rows"}


# ------------------------------------------------------------ value cleaning
_SPACES = "  "  # non-breaking spaces used as thousands separators
_CURRENCY = re.compile(r"[$€£]")  # $ EUR-sign GBP-sign

_PLAIN = re.compile(r"^\d+(\.\d+)?$")                    # 1200  3.5
_US_GROUPED = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")  # 1,200  1,200.50
_SPACE_GROUPED = re.compile(r"^\d{1,3}( \d{3})+([.,]\d+)?$")  # 1 234  1 234,56
_EU_GROUPED = re.compile(r"^\d{1,3}(\.\d{3})+,\d+$")     # 1.234,56
_COMMA_DECIMAL = re.compile(r"^\d+,\d+$")                # 3,14  (not exactly 3 decimals)
_BRACKET_MINUS = re.compile(r"^\(\s*[-−–]\s*\)\s*(.+)$")  # (-) 100.000
_EU_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3}){2,}$")       # 1.234.567 (2+ dot groups, no decimals)


def parse_number(text: str):
    """Return an int/float for a number written in a common format, else None.

    Handled: 1200, 1,200, 1,200.50, 1 234,56, 1.234,56, 1.234.567, 3,14, -5, (120) = -120,
    (-) 100 = -100, and a leading/trailing currency sign ($ EUR GBP).
    NOT handled on purpose: a lone dash "-" (accounting "nil") stays text, and percentages ("12%") and text with units ("5 TND"): they stay text.
    Ambiguity: "1,500" is read as one thousand five hundred (comma + exactly 3 digits = thousands),
    but "1.500" stays 1.5 (a single dot group is read as a decimal point).
    """
    s = text.strip()
    for ch in _SPACES:
        s = s.replace(ch, " ")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    s = _CURRENCY.sub("", s).strip()
    # accounting style "(-) 100.000" / "(-)100.000" / "(–) 100": a minus sign inside brackets
    bracket_minus = _BRACKET_MINUS.match(s)
    if bracket_minus:
        negative, s = True, _CURRENCY.sub("", bracket_minus.group(1)).strip()
    if s[:1] in "-−":
        negative, s = True, s[1:].strip()
    elif s[:1] == "+":
        s = s[1:].strip()
    if not s:
        return None
    if _PLAIN.match(s):
        number = float(s)
    elif _US_GROUPED.match(s):
        number = float(s.replace(",", ""))
    elif _SPACE_GROUPED.match(s):
        number = float(s.replace(" ", "").replace(",", "."))
    elif _EU_THOUSANDS.match(s):
        number = float(s.replace(".", ""))
    elif _EU_GROUPED.match(s):
        number = float(s.replace(".", "").replace(",", "."))
    elif _COMMA_DECIMAL.match(s):
        number = float(s.replace(",", "."))
    else:
        return None
    if negative:
        number = -number
    return int(number) if number.is_integer() else number


def clean_cell(value):
    """Turn '1,200' -> 1200, '3.5' -> 3.5, '(120)' -> -120, keep everything else as text.

    Empty / NaN cells become None so the harness can detect missing cells.
    See parse_number() for the formats handled.
    """
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else float(value)
    text = str(value).strip()
    if text == "":
        return None
    number = parse_number(text)
    return text if number is None else number


def flatten_columns(columns) -> list[str]:
    """Docling can return multi-level headers; join the levels into one string."""
    flat = []
    for col in columns:
        if isinstance(col, tuple):
            parts = [str(p) for p in col if str(p).strip() and not str(p).startswith("Unnamed")]
            flat.append(" ".join(parts))
        else:
            flat.append(str(col))
    return flat


# ------------------------------------------------------------ table contract
def dataframe_to_contract(df: pd.DataFrame, doc_id: str, page: int, index: int) -> dict:
    """Build the JSON dict that the harness, the Q&A layer and the automation consume.

    {
      "doc_id": "report1", "table_id": "report1_p3_t1", "page": 3,
      "columns": [...], "rows": [[...], ...]
    }
    """
    return {
        "doc_id": doc_id,
        "table_id": f"{doc_id}_p{page}_t{index}",
        "page": page,
        "columns": flatten_columns(df.columns),
        "rows": [[clean_cell(v) for v in row] for row in df.itertuples(index=False)],
    }


def validate_contract(table: dict) -> list[str]:
    """Return a list of problems with the *format* (not the numbers)."""
    problems = []
    missing = REQUIRED_KEYS - set(table)
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
        return problems
    if not isinstance(table["page"], int) or table["page"] < 0:
        problems.append("page must be a non-negative integer")
    if not isinstance(table["columns"], list) or not table["columns"]:
        problems.append("columns must be a non-empty list")
    if not isinstance(table["rows"], list):
        problems.append("rows must be a list of lists")
    return problems
