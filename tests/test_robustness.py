"""Tolerance tests: number formats, retry cascade, error isolation, multi-format input."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import convert as engine
from engine.contract import clean_cell, parse_number


# ------------------------------------------------------------- number formats
@pytest.mark.parametrize("raw,expected", [
    ("1200", 1200), ("1,200", 1200), ("1,200.50", 1200.5), ("3.5", 3.5),
    ("1 234,56", 1234.56), ("1 234", 1234), ("1.234,56", 1234.56),
    ("3,14", 3.14), ("-5", -5), ("(120)", -120), ("$40", 40), ("€ 1 000", 1000),
    ("+7", 7), ("−2", -2),
])
def test_parse_number_formats(raw, expected):
    assert parse_number(raw) == expected
    assert clean_cell(raw) == expected


@pytest.mark.parametrize("raw", ["Total", "12%", "5 TND", "-", "—", "$", "1,2,3", "12abc", "1..2"])
def test_not_numbers_stay_text(raw):
    assert parse_number(raw) is None
    assert clean_cell(raw) == raw


def test_ambiguous_comma_three_digits_is_thousands():
    assert parse_number("1,500") == 1500  # documented ambiguity


# ------------------------------------------------------------------ planning
def test_plan_for_non_pdf_is_single_attempt():
    assert engine.plan_attempts(Path("a.docx"), False, False, False, True) == ["default"]


def test_plan_for_pdf_cascade():
    assert engine.plan_attempts(Path("a.pdf"), False, False, False, True) == [
        "fast", "accurate", "ocr+accurate"]
    assert engine.plan_attempts(Path("a.pdf"), True, False, False, True) == ["accurate", "ocr+accurate"]
    assert engine.plan_attempts(Path("a.pdf"), False, False, True, True)[-1] == "vlm"
    assert engine.plan_attempts(Path("a.pdf"), False, False, False, False) == ["fast"]


def test_doc_id_does_not_clash_between_formats():
    assert engine.doc_id_for(Path("report.pdf")) == "report"
    assert engine.doc_id_for(Path("report.docx")) == "report_docx"


def test_find_files_filters_unsupported(tmp_path):
    for name in ("a.pdf", "b.docx", "c.txt", "d.PNG", "e.zip"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in engine.find_files(tmp_path)] == ["a.pdf", "b.docx", "d.PNG"]


# ------------------------------------------------------------ fake converters
class FakeTable:
    def __init__(self):
        import pandas as pd
        self.prov = [SimpleNamespace(page_no=1)]
        self._df = pd.DataFrame([["A", "5"]], columns=["Item", "Q1"])

    def export_to_dataframe(self, doc=None):
        return self._df


class FakeDoc:
    def __init__(self, n_tables):
        self.tables = [FakeTable() for _ in range(n_tables)]

    def export_to_markdown(self):
        return "# fake"

    def export_to_dict(self):
        return {"fake": True}


class FakeConverter:
    def __init__(self, n_tables=0, error=None):
        self.n_tables, self.error, self.calls = n_tables, error, 0

    def convert(self, path):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(document=FakeDoc(self.n_tables))


def run(tmp_path, plan, converters):
    return engine.process_file(tmp_path / "x.pdf", tmp_path / "out", plan, converters.__getitem__)


def test_cascade_stops_at_first_attempt_with_tables(tmp_path):
    conv = {"fast": FakeConverter(0), "accurate": FakeConverter(1), "ocr+accurate": FakeConverter(1)}
    summary = run(tmp_path, ["fast", "accurate", "ocr+accurate"], conv)
    assert summary["status"] == "ok" and summary["mode"] == "accurate" and summary["n_tables"] == 1
    assert [a["mode"] for a in summary["attempts"]] == ["fast", "accurate"]
    assert conv["ocr+accurate"].calls == 0


def test_cascade_all_empty_gives_no_tables_and_warning(tmp_path):
    conv = {"fast": FakeConverter(0), "accurate": FakeConverter(0)}
    summary = run(tmp_path, ["fast", "accurate"], conv)
    assert summary["status"] == "no_tables" and "0 tables found" in summary["warning"]
    assert len(summary["attempts"]) == 2


class EmptyOutlineTable(FakeTable):
    """What Docling returns for a table on a scanned page read WITHOUT OCR: no cells at all."""

    def export_to_dataframe(self, doc=None):
        import pandas as pd
        return pd.DataFrame()


class ScanConverter(FakeConverter):
    def convert(self, path):
        self.calls += 1
        doc = FakeDoc(0)
        doc.tables = [EmptyOutlineTable() for _ in range(3)]
        return SimpleNamespace(document=doc)


def test_empty_table_outlines_do_not_stop_the_cascade(tmp_path):
    """Bug fix: a scanned PDF gave 3 EMPTY tables without OCR and the cascade stopped there."""
    conv = {"fast": ScanConverter(), "accurate": ScanConverter(), "ocr+accurate": FakeConverter(2)}
    summary = run(tmp_path, ["fast", "accurate", "ocr+accurate"], conv)
    assert summary["mode"] == "ocr+accurate" and summary["n_tables"] == 2
    assert summary["attempts"][0] == {"mode": "fast", "n_tables": 3, "n_usable": 0, "error": None}


def test_only_empty_tables_gives_a_clear_warning(tmp_path):
    summary = run(tmp_path, ["fast"], {"fast": ScanConverter()})
    assert summary["n_tables"] == 3 and "--ocr" in summary["warning"]


def test_plan_for_images_always_uses_ocr():
    assert engine.plan_attempts(Path("scan.jpeg"), False, False, False, True) == [
        "ocr+fast", "ocr+accurate"]
    assert engine.plan_attempts(Path("scan.png"), True, False, True, True) == ["ocr+accurate"]


def test_error_in_first_attempt_falls_through_to_next(tmp_path):
    conv = {"fast": FakeConverter(error=RuntimeError("boom")), "accurate": FakeConverter(1)}
    summary = run(tmp_path, ["fast", "accurate"], conv)
    assert summary["status"] == "ok"
    assert summary["attempts"][0]["error"] == "RuntimeError: boom"


def test_all_attempts_fail_gives_failed_status_without_raising(tmp_path):
    conv = {"fast": FakeConverter(error=ValueError("bad file"))}
    summary = run(tmp_path, ["fast"], conv)
    assert summary["status"] == "failed" and "bad file" in summary["error"]
    saved = json.loads((tmp_path / "out" / "x" / "summary.json").read_text(encoding="utf-8"))
    assert saved["status"] == "failed"


def test_reconversion_does_not_leave_stale_tables(tmp_path):
    """Converting the same file again must not keep the tables of the previous run."""
    run(tmp_path, ["fast"], {"fast": FakeConverter(3)})
    tables = tmp_path / "out" / "x" / "tables"
    assert len(list(tables.glob("*.json"))) == 3
    run(tmp_path, ["fast"], {"fast": FakeConverter(1)})
    assert [p.name for p in tables.glob("*.json")] == ["x_p1_t1.json"]
    summary = run(tmp_path, ["fast"], {"fast": FakeConverter(error=ValueError("bad"))})
    assert summary["status"] == "failed" and not list(tables.glob("*.json"))
    assert not (tmp_path / "out" / "x" / "x.md").exists()


def test_main_continues_after_a_failed_file(tmp_path, monkeypatch, capsys):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a.pdf").write_bytes(b"x")
    (tmp_path / "in" / "b.pdf").write_bytes(b"x")

    def fake_make(mode):
        class C:
            def convert(self, path):
                if path.name == "a.pdf":
                    raise RuntimeError("cannot read a")
                return SimpleNamespace(document=FakeDoc(1))
        return C()

    monkeypatch.setattr(engine, "make_converter", fake_make)
    code = engine.main([str(tmp_path / "in"), "--out", str(tmp_path / "out"), "--no-fallback"])
    out = capsys.readouterr().out
    assert code == 2  # a failure is signalled to scripts
    assert "a.pdf: 0 table(s) [failed]" in out and "b.pdf: 1 table(s) [ok]" in out
    report = json.loads((tmp_path / "out" / "run_report.json").read_text(encoding="utf-8"))
    assert report["counts"] == {"ok": 1, "no_tables": 0, "failed": 1}


# ------------------------------------------------- real Docling, no AI models
def test_real_docling_reads_an_excel_file(tmp_path):
    """Excel is parsed without any AI model, so this runs anywhere Docling is installed."""
    pytest.importorskip("docling")
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in [["Item", "Q1", "Q2", "Total"], ["A", 10, 20, 30], ["Total", 10, 20, 30]]:
        ws.append(row)
    path = tmp_path / "budget.xlsx"
    wb.save(path)
    summary = engine.process_file(path, tmp_path / "out", ["default"], engine.make_converter)
    assert summary["status"] == "ok" and summary["doc_id"] == "budget_xlsx"
    table = json.loads(next((tmp_path / "out" / "budget_xlsx" / "tables").glob("*.json")).read_text())
    assert table["rows"][-1] == ["Total", 10, 20, 30]


def test_real_docling_isolates_a_corrupt_file(tmp_path):
    pytest.importorskip("docling")
    bad = tmp_path / "broken.docx"
    bad.write_text("this is not a real docx file")
    summary = engine.process_file(bad, tmp_path / "out", ["default"], engine.make_converter)
    assert summary["status"] == "failed"


def test_parse_number_bracket_minus():
    assert parse_number("(-) 100.000") == -100
    assert parse_number("(-)100.000") == -100
    assert parse_number("(-)") is None
