"""Export contract tables (engine/contract.py format) to CSV, JSON, Markdown and one Excel workbook."""
from __future__ import annotations

import io
import json
import re

import pandas as pd


def table_to_dataframe(table: dict) -> pd.DataFrame:
    """Contract table -> DataFrame.

    Ragged rows (flagged by the harness as COLUMN_COUNT) are padded with empty cells, and
    extra cells get an `extra_N` header, so a broken table can still be shown and exported.
    """
    columns = list(table["columns"])
    width = max([len(columns)] + [len(row) for row in table["rows"]])
    columns += [f"extra_{n}" for n in range(len(columns) + 1, width + 1)]
    rows = [list(row) + [None] * (width - len(row)) for row in table["rows"]]
    # dtype=object keeps each value as extracted (an empty cell does not turn 2 into 2.0)
    return pd.DataFrame(rows, columns=columns, dtype=object)


def table_to_csv_bytes(table: dict) -> bytes:
    return table_to_dataframe(table).to_csv(index=False).encode("utf-8-sig")  # utf-8-sig: Excel-friendly


def table_to_json_bytes(table: dict) -> bytes:
    return json.dumps(table, ensure_ascii=False, indent=2).encode("utf-8")


def _markdown_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    # a "|" or a line break inside a cell would break the Markdown table
    return str(value).replace("|", "\\|").replace("\n", " ")


def table_to_markdown(table: dict) -> str:
    """A contract table as a Markdown table (header row, separator, one line per row)."""
    lines = [
        "| " + " | ".join(_markdown_cell(c) for c in table["columns"]) + " |",
        "| " + " | ".join("---" for _ in table["columns"]) + " |",
    ]
    for row in table["rows"]:
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def table_to_markdown_bytes(table: dict) -> bytes:
    return (table_to_markdown(table) + "\n").encode("utf-8")


def _sheet_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "_", name)[:31] or "table"
    candidate, n = base, 2
    while candidate.lower() in used:  # Excel sheet names: unique, max 31 chars
        suffix = f"_{n}"
        candidate = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(candidate.lower())
    return candidate


def tables_to_xlsx_bytes(tables: list[dict]) -> bytes:
    """One sheet per table. Numeric cells stay numeric; an empty list gives a 'no tables' sheet."""
    buffer = io.BytesIO()
    used: set[str] = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if not tables:
            pd.DataFrame({"info": ["no tables"]}).to_excel(writer, sheet_name="no_tables", index=False)
        for table in tables:
            name = _sheet_name(table.get("table_id", "table"), used)
            table_to_dataframe(table).to_excel(writer, sheet_name=name, index=False)
    return buffer.getvalue()
