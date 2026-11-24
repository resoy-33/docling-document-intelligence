"""Tests that do NOT need Docling models: contract format, cleaning, fixtures."""
import json
from pathlib import Path

import pandas as pd
import pytest

from engine.contract import (clean_cell, dataframe_to_contract,
                             flatten_columns, validate_contract)

FIXTURES = sorted(Path(__file__).parent.parent.joinpath("fixtures").glob("*.json"))


@pytest.mark.parametrize("raw,expected", [
    ("12", 12), ("1,200", 1200), ("3.5", 3.5), ("  7 ", 7),
    ("Total", "Total"), ("", None), (None, None), (float("nan"), None),
    (4.0, 4), (2.5, 2.5),
    # formats seen in the BIAT annual report and other French/Tunisian statements
    ("2 776 490", 2776490), ("1.234.567", 1234567),
    ("1.500", 1.5), ("12%", "12%"), ("5 TND", "5 TND"),
])
def test_clean_cell(raw, expected):
    assert clean_cell(raw) == expected


def test_flatten_multiindex_columns():
    cols = pd.MultiIndex.from_tuples([("Sales", "Q1"), ("Sales", "Q2"), ("Unnamed: 2", "Total")])
    assert flatten_columns(cols) == ["Sales Q1", "Sales Q2", "Total"]


def test_dataframe_to_contract_shape():
    df = pd.DataFrame([["A", "10", "20"], ["Total", "10", "20"]], columns=["Item", "Q1", "Q2"])
    t = dataframe_to_contract(df, doc_id="report1", page=3, index=1)
    assert t["table_id"] == "report1_p3_t1"
    assert t["page"] == 3
    assert t["columns"] == ["Item", "Q1", "Q2"]
    assert t["rows"] == [["A", 10, 20], ["Total", 10, 20]]
    assert validate_contract(t) == []


def test_empty_cell_becomes_null():
    df = pd.DataFrame([["A", ""]], columns=["Item", "Q1"])
    assert dataframe_to_contract(df, "d", 1, 1)["rows"] == [["A", None]]


def test_fixtures_exist_and_follow_contract():
    assert len(FIXTURES) >= 5
    for path in FIXTURES:
        table = json.loads(path.read_text(encoding="utf-8"))
        assert validate_contract(table) == [], path.name
        # every table_id embeds its doc_id and page, like real output
        assert table["table_id"].startswith(f"{table['doc_id']}_p{table['page']}_t")


def test_validate_contract_flags_missing_keys():
    assert validate_contract({"doc_id": "x"})


def test_extract_tables_with_stub_document():
    """Checks page numbering and per-page counters without running Docling."""
    from types import SimpleNamespace
    from engine.convert import extract_tables

    class FakeTable:
        def __init__(self, page, rows):
            self.prov = [SimpleNamespace(page_no=page)]
            self._df = pd.DataFrame(rows, columns=["Item", "Q1"])

        def export_to_dataframe(self, doc=None):
            return self._df

    doc = SimpleNamespace(tables=[
        FakeTable(1, [["A", "5"]]),
        FakeTable(1, [["B", "6"]]),
        FakeTable(3, [["C", "7"]]),
    ])
    out = extract_tables(doc, "report")
    assert [t["table_id"] for t in out] == ["report_p1_t1", "report_p1_t2", "report_p3_t1"]
    assert out[2]["rows"] == [["C", 7]]
