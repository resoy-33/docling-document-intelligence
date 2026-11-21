"""Tests of the verification harness.

Ground truth = good tables (must pass) and deliberately corrupted ones (must fail
for the RIGHT reason). Run from the project root:  python -m pytest -q

Fixtures: the 5 JSON files of Member 1 must be in tests/fixtures/ (or fixtures/).
"""
import copy
import json
from pathlib import Path

import pytest

from harness import FailureCode, TableResult, validate_table
from harness.checks import find_total_col, find_total_row
from harness.validate import validate_directory, validate_file, verified_tables

HERE = Path(__file__).parent
FIXTURES = next((p for p in (HERE / "fixtures", HERE.parent / "fixtures") if p.is_dir()), HERE / "fixtures")

GOOD = {
    "doc_id": "t", "table_id": "t_p1_t1", "page": 1,
    "columns": ["Item", "Q1", "Q2", "Total"],
    "rows": [["A", 10, 20, 30], ["B", 5, 5, 10], ["Total", 15, 25, 40]],
}

# Same numbers as sample_wrong_total.pdf (make_samples.py): the grand total says 1300, real value 1250.
SALES_COLUMNS = ["Item", "Q1", "Q2", "Q3", "Total"]
SALES_ROWS = [
    ["Laptops", 120, 135, 150, 405],
    ["Phones", 200, 180, 220, 600],
    ["Tablets", 80, 95, 70, 245],
    ["Total", 400, 410, 440, 1250],
]


def make(**changes) -> TableResult:
    data = copy.deepcopy(GOOD)
    data.update(changes)
    return TableResult.model_validate(data)


def codes(report) -> list[str]:
    return [f.code.value for f in report.failures]


# ------------------------------------------------------------- Member 1 fixtures
@pytest.mark.parametrize("name", ["good_table_1", "good_table_2"])
def test_good_fixtures_pass(name):
    report = validate_file(FIXTURES / f"{name}.json")
    assert report.passed, report.failures
    assert report.verifiable


def test_wrong_total_fixture_fails():
    report = validate_file(FIXTURES / "wrong_total.json")
    assert not report.passed
    assert FailureCode.COLUMN_TOTAL_MISMATCH.value in codes(report)
    assert "99" in report.failures[0].message and "40" in report.failures[0].message


def test_missing_cell_fixture_fails():
    report = validate_file(FIXTURES / "missing_cell.json")
    assert codes(report) == ["EMPTY_CELL"]
    assert (report.failures[0].row, report.failures[0].col) == (0, 2)


def test_ragged_columns_fixture_fails():
    report = validate_file(FIXTURES / "ragged_columns.json")
    assert codes(report) == ["COLUMN_COUNT"]
    assert report.failures[0].row == 1


# ------------------------------------------------------------- corrupted tables
def test_good_table_passes():
    assert validate_table(make()).passed


def test_one_wrong_cell_is_caught_by_both_sums():
    rows = copy.deepcopy(GOOD["rows"])
    rows[0][1] = 11  # A/Q1: 10 -> 11
    report = validate_table(make(rows=rows))
    assert set(codes(report)) == {"ROW_TOTAL_MISMATCH", "COLUMN_TOTAL_MISMATCH"}


def test_sales_table_with_wrong_grand_total():
    rows = copy.deepcopy(SALES_ROWS)
    assert validate_table(make(columns=SALES_COLUMNS, rows=rows)).passed
    rows[-1][-1] = 1300
    report = validate_table(make(columns=SALES_COLUMNS, rows=rows))
    assert not report.passed
    assert any("1250" in f.message and "1300" in f.message for f in report.failures)


def test_text_in_numeric_column():
    rows = copy.deepcopy(GOOD["rows"])
    rows[1][2] = "5O"  # letter O instead of zero (typical OCR error)
    report = validate_table(make(rows=rows))
    assert "NON_NUMERIC" in codes(report)


def test_blank_string_is_an_empty_cell():
    rows = copy.deepcopy(GOOD["rows"])
    rows[1][1] = "  "
    assert "EMPTY_CELL" in codes(validate_table(make(rows=rows)))


def test_rounding_tolerance():
    rows = [["A", 10.004, 20, 30], ["Total", 10.004, 20, 30]]
    assert validate_table(make(rows=rows)).passed
    rows = [["A", 10.5, 20, 30], ["Total", 10.5, 20, 30]]
    assert not validate_table(make(rows=rows)).passed
    assert validate_table(make(rows=rows), tol=1).passed


def test_french_total_labels_and_text_column_ignored():
    table = make(
        columns=["Produit", "Catégorie", "Jan", "Fév", "Totale"],
        rows=[["A", "x", 1, 2, 3], ["B", "y", 4, 5, 9], ["TOTAL", "", 5, 7, 12]],
    )
    # the empty cell in the text column is still reported, but no false total mismatch
    assert codes(validate_table(table)) == ["EMPTY_CELL"]
    assert find_total_row(table) == 2 and find_total_col(table) == 4


def test_table_without_totals_is_structural_only():
    table = make(columns=["Name", "Age"], rows=[["Ali", 30], ["Sara", 25]])
    report = validate_table(table)
    assert report.passed and not report.verifiable
    strict = validate_table(table, require_totals=True)
    assert codes(strict) == ["NO_TOTALS"]


def test_total_column_only():
    table = make(columns=["Item", "Q1", "Q2", "Total"], rows=[["A", 1, 2, 4]])
    assert codes(validate_table(table)) == ["ROW_TOTAL_MISMATCH"]


def test_ragged_table_does_not_crash_total_checks():
    table = make(rows=[["A", 10, 20, 30], ["B", 5], ["Total", 15, 25, 40, 7]])
    report = validate_table(table)
    assert codes(report) == ["COLUMN_COUNT", "COLUMN_COUNT"]


# ----------------------------------------------------------------- file level
def test_invalid_json_and_bad_contract(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "nokeys.json").write_text(json.dumps({"doc_id": "x"}), encoding="utf-8")
    for name in ("broken.json", "nokeys.json"):
        report = validate_file(tmp_path / name)
        assert codes(report) == ["INVALID_FORMAT"]


# ------------------------------------------------------------- folder + rates
def _write_doc(root: Path, doc_id: str, status: str, tables: list[dict], error: str | None = None):
    folder = root / doc_id
    (folder / "tables").mkdir(parents=True)
    info = {"doc_id": doc_id, "status": status, "n_tables": len(tables)}
    if error:
        info["error"] = error
    (folder / "summary.json").write_text(json.dumps(info), encoding="utf-8")
    for t in tables:
        (folder / "tables" / f"{t['table_id']}.json").write_text(json.dumps(t), encoding="utf-8")


def _table(doc_id: str, rows=None) -> dict:
    t = copy.deepcopy(GOOD)
    t["doc_id"], t["table_id"] = doc_id, f"{doc_id}_p1_t1"
    if rows:
        t["rows"] = rows
    return t


def build_output(root: Path):
    bad_rows = copy.deepcopy(GOOD["rows"])
    bad_rows[2][3] = 99
    _write_doc(root, "ok_doc", "ok", [_table("ok_doc")])
    _write_doc(root, "bad_doc", "ok", [_table("bad_doc", bad_rows)])
    _write_doc(root, "empty_doc", "no_tables", [])
    _write_doc(root, "failed_doc", "failed", [], error="RuntimeError: boom")


def test_pass_rates_count_zero_tables_and_failed_as_failures(tmp_path):
    build_output(tmp_path)
    summary = validate_directory(tmp_path)
    assert summary.n_docs == 4 and summary.n_docs_passed == 1
    assert summary.n_tables == 2 and summary.n_tables_passed == 1
    assert summary.pass_rate_tables == 0.5
    assert summary.pass_rate_docs == 0.25
    issues = {i.doc_id: i.code.value for i in summary.doc_issues}
    assert issues == {"empty_doc": "NO_TABLES", "failed_doc": "EXTRACTION_FAILED"}


def test_verified_tables_only_returns_passing_tables(tmp_path):
    build_output(tmp_path)
    ids = [t.table_id for t in verified_tables(tmp_path)]
    assert ids == ["ok_doc_p1_t1"]


def test_report_is_json_serialisable(tmp_path):
    build_output(tmp_path)
    data = json.loads(validate_directory(tmp_path).model_dump_json())
    assert data["pass_rate_docs"] == 0.25
    assert data["reports"][0]["passed"] in (True, False)
