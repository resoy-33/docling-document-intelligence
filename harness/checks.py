"""Deterministic checksum rules (pure Python, no I/O, no AI).

Every rule returns a list of Failure. validate_table() runs them all and builds the verdict.

Rules
  column_count     every row has exactly len(columns) cells
  empty_cells      no null / blank cell
  numeric_cells    no text inside a numeric column (a mis-read number such as "1 2OO")
  row_totals       for each row: sum of the value cells == the cell of the "Total" column
  column_totals    for each column: sum of the data rows == the cell of the "Total" row

How totals are found
  Total row     the LAST row whose first cell is a total label ("Total", "Totale", "Totaux", ...)
  Total column  the RIGHTMOST column (not the first) whose header is a total label
  A column is "numeric" if at least half of its non-empty cells are numbers (the Total
  column always is). The first column is the row label and is never summed.

Limits (on purpose, keep the rules simple and explainable)
  - one Total row / one Total column per table, no sub-totals
  - tables without any total can only be checked structurally (see require_totals)
"""
import math

from .models import Failure, FailureCode, TableResult, ValidationReport

DEFAULT_TOL = 0.01  # absolute tolerance, covers rounding of currency amounts

TOTAL_LABELS = {
    "total", "totals", "grand total", "sum",
    "totale", "totaux", "total general", "total général", "somme",
}

CHECK_COLUMN_COUNT = "column_count"
CHECK_EMPTY_CELLS = "empty_cells"
CHECK_NUMERIC_CELLS = "numeric_cells"
CHECK_ROW_TOTALS = "row_totals"
CHECK_COLUMN_TOTALS = "column_totals"


# ------------------------------------------------------------------ helpers
def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _norm(label) -> str:
    return str(label).strip().casefold().rstrip(":").strip()


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.2f}".rstrip("0").rstrip(".")


def _row_label(row: list) -> str:
    return str(row[0]) if row and not is_blank(row[0]) else "?"


def find_total_row(table: TableResult) -> int | None:
    for i in range(len(table.rows) - 1, -1, -1):
        row = table.rows[i]
        if row and isinstance(row[0], str) and _norm(row[0]) in TOTAL_LABELS:
            return i
    return None


def find_total_col(table: TableResult) -> int | None:
    for j in range(len(table.columns) - 1, 0, -1):
        if _norm(table.columns[j]) in TOTAL_LABELS:
            return j
    return None


def numeric_columns(table: TableResult, total_col: int | None) -> list[int]:
    """Indexes of the columns that hold numbers (never column 0). Rows must be rectangular."""
    cols = []
    for j in range(1, len(table.columns)):
        values = [row[j] for row in table.rows if not is_blank(row[j])]
        numbers = sum(1 for v in values if is_number(v))
        if j == total_col or (values and numbers * 2 >= len(values)):
            cols.append(j)
    return cols


# -------------------------------------------------------------------- rules
def check_column_count(table: TableResult) -> list[Failure]:
    expected = len(table.columns)
    return [
        Failure(
            code=FailureCode.COLUMN_COUNT,
            row=i,
            message=f"row {i + 1} ({_row_label(row)}) has {len(row)} cells, expected {expected}",
        )
        for i, row in enumerate(table.rows)
        if len(row) != expected
    ]


def check_empty_cells(table: TableResult) -> list[Failure]:
    failures = []
    for i, row in enumerate(table.rows):
        for j, value in enumerate(row):
            if is_blank(value):
                name = table.columns[j] if j < len(table.columns) else f"#{j + 1}"
                failures.append(Failure(
                    code=FailureCode.EMPTY_CELL, row=i, col=j,
                    message=f"empty cell at row {i + 1} ({_row_label(row)}), column '{name}'",
                ))
    return failures


def check_totals(
    table: TableResult, tol: float = DEFAULT_TOL, require_totals: bool = False
) -> tuple[list[Failure], list[str]]:
    """Numeric rules. Returns (failures, names of the checks that actually ran)."""
    failures: list[Failure] = []
    ran: list[str] = []
    n_cols = len(table.columns)

    if any(len(row) != n_cols for row in table.rows):
        return failures, ran  # broken structure: already reported by check_column_count

    total_row = find_total_row(table)
    total_col = find_total_col(table)
    if total_row is None and total_col is None:
        if require_totals:
            failures.append(Failure(
                code=FailureCode.NO_TOTALS,
                message="no Total row and no Total column: nothing to verify",
            ))
        return failures, ran

    num_cols = numeric_columns(table, total_col)

    ran.append(CHECK_NUMERIC_CELLS)
    for i, row in enumerate(table.rows):
        for j in num_cols:
            value = row[j]
            if not is_blank(value) and not is_number(value):
                failures.append(Failure(
                    code=FailureCode.NON_NUMERIC, row=i, col=j,
                    message=f"text '{value}' in numeric column '{table.columns[j]}' "
                            f"at row {i + 1} ({_row_label(row)})",
                ))

    if total_col is not None:
        ran.append(CHECK_ROW_TOTALS)
        sum_cols = [j for j in num_cols if j != total_col]
        for i, row in enumerate(table.rows):
            cells = [row[j] for j in sum_cols]
            if not sum_cols or not all(is_number(c) for c in cells + [row[total_col]]):
                continue  # missing / text cell: reported by another rule
            expected = math.fsum(cells)
            if abs(expected - row[total_col]) > tol:
                failures.append(Failure(
                    code=FailureCode.ROW_TOTAL_MISMATCH, row=i, col=total_col,
                    message=f"row {i + 1} ({_row_label(row)}): cells add up to {_fmt(expected)} "
                            f"but '{table.columns[total_col]}' says {_fmt(row[total_col])}",
                ))

    if total_row is not None:
        ran.append(CHECK_COLUMN_TOTALS)
        data_rows = [i for i in range(len(table.rows)) if i != total_row]
        for j in num_cols:
            cells = [table.rows[i][j] for i in data_rows]
            total_cell = table.rows[total_row][j]
            if not cells or not all(is_number(c) for c in cells + [total_cell]):
                continue
            expected = math.fsum(cells)
            if abs(expected - total_cell) > tol:
                failures.append(Failure(
                    code=FailureCode.COLUMN_TOTAL_MISMATCH, row=total_row, col=j,
                    message=f"column '{table.columns[j]}': rows add up to {_fmt(expected)} "
                            f"but the Total row says {_fmt(total_cell)}",
                ))

    return failures, ran


# ------------------------------------------------------------------ verdict
def validate_table(
    table: TableResult, tol: float = DEFAULT_TOL, require_totals: bool = False
) -> ValidationReport:
    """Run every rule on one table and return the pass/fail verdict with all reasons."""
    failures = check_column_count(table) + check_empty_cells(table)
    checks = [CHECK_COLUMN_COUNT, CHECK_EMPTY_CELLS]
    total_failures, ran = check_totals(table, tol=tol, require_totals=require_totals)
    return ValidationReport(
        doc_id=table.doc_id,
        table_id=table.table_id,
        page=table.page,
        failures=failures + total_failures,
        checks_run=checks + ran,
    )
