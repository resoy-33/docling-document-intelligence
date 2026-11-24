"""End-to-end tests with the REAL Docling models: engine -> contract JSON -> harness verdict.

Skipped automatically when Docling is not installed (light install). They are slower than the
other tests (about 1 minute on a laptop CPU; the first run also downloads the models).
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("docling")

from engine import convert as engine  # noqa: E402
from harness.validate import validate_directory  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
_CONVERTERS: dict = {}


def get_converter(mode: str):
    """Build each Docling converter once for the whole test module (loading models is slow)."""
    if mode not in _CONVERTERS:
        _CONVERTERS[mode] = engine.make_converter(mode)
    return _CONVERTERS[mode]


def convert(path: Path, out: Path) -> dict:
    plan = engine.plan_attempts(path, accurate=False, ocr=False, vlm=False, fallback=True)
    return engine.process_file(path, out, plan, get_converter)


def read_tables(out: Path, doc_id: str) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((out / doc_id / "tables").glob("*.json"))]


def test_correct_pdf_table_passes_the_checksums(tmp_path):
    summary = convert(SAMPLES / "sample_simple_table.pdf", tmp_path)
    assert summary["status"] == "ok" and summary["n_tables"] == 1
    table = read_tables(tmp_path, "sample_simple_table")[0]
    assert table["columns"] == ["Item", "Q1", "Q2", "Q3", "Total"]
    assert table["rows"][-1] == ["Total", 400, 410, 440, 1250]
    for name in ("sample_simple_table.md", "sample_simple_table.docling.json"):
        assert (tmp_path / "sample_simple_table" / name).exists()
    batch = validate_directory(tmp_path)
    assert batch.n_tables_passed == 1 and batch.reports[0].verifiable


def test_wrong_total_pdf_is_flagged(tmp_path):
    convert(SAMPLES / "sample_wrong_total.pdf", tmp_path)
    report = validate_directory(tmp_path).reports[0]
    assert not report.passed
    assert {f.code.value for f in report.failures} >= {"COLUMN_TOTAL_MISMATCH"}


def test_docx_table_is_extracted_and_validated(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Budget 2026", level=1)
    rows = [["Item", "Q1", "Q2", "Total"], ["Rent", "100", "100", "200"],
            ["Salaries", "300", "350", "650"], ["Total", "400", "450", "850"]]
    grid = document.add_table(rows=len(rows), cols=len(rows[0]))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            grid.cell(i, j).text = value
    path = tmp_path / "budget.docx"
    document.save(path)

    summary = convert(path, tmp_path / "out")
    assert summary["status"] == "ok" and summary["doc_id"] == "budget_docx"
    table = read_tables(tmp_path / "out", "budget_docx")[0]
    assert table["rows"][-1] == ["Total", 400, 450, 850]
    assert validate_directory(tmp_path / "out").n_tables_passed == 1


def test_scanned_pdf_falls_through_to_ocr(tmp_path):
    """scan_invoice.pdf has no text layer: without OCR its tables are empty outlines."""
    summary = convert(SAMPLES / "scan_invoice.pdf", tmp_path)
    assert summary["mode"].startswith("ocr")
    assert summary["attempts"][0]["n_usable"] == 0
    tables = read_tables(tmp_path, "scan_invoice")
    assert tables and all(t["columns"] for t in tables)
    assert any("Amount" in t["columns"] for t in tables)  # the line-items table was read by OCR
