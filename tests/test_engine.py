"""Engine tests that need no Docling models: a fake converter stands in for Docling."""
import json
from types import SimpleNamespace

import pandas as pd

from engine import convert as engine
from baseline.compare_report import build_report, count_tables


class FakeTable:
    def __init__(self, page, rows):
        self.prov = [SimpleNamespace(page_no=page)]
        self._df = pd.DataFrame(rows, columns=["Item", "Q1", "Total"])

    def export_to_dataframe(self, doc=None):
        return self._df


class FakeDoc:
    def __init__(self, tables):
        self.tables = tables

    def export_to_markdown(self):
        return "# fake"

    def export_to_dict(self):
        return {"fake": True}


class FakeConverter:
    def __init__(self, tables):
        self._tables = tables

    def convert(self, path):
        return SimpleNamespace(document=FakeDoc(self._tables))


def test_convert_pdf_writes_all_outputs(tmp_path):
    conv = FakeConverter([FakeTable(1, [["A", "5", "5"], ["Total", "5", "5"]])])
    tables = engine.convert_pdf(tmp_path / "report.pdf", tmp_path / "out", conv)
    assert [t["table_id"] for t in tables] == ["report_p1_t1"]
    base = tmp_path / "out" / "report"
    assert (base / "report.md").read_text(encoding="utf-8") == "# fake"
    assert json.loads((base / "report.docling.json").read_text(encoding="utf-8")) == {"fake": True}
    saved = json.loads((base / "tables" / "report_p1_t1.json").read_text(encoding="utf-8"))
    assert saved["rows"] == [["A", 5, 5], ["Total", 5, 5]]
    assert (base / "tables" / "report_p1_t1.csv").exists()
    summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    assert summary["n_tables"] == 1 and "warning" not in summary


def test_zero_tables_is_reported_in_summary(tmp_path):
    tables = engine.convert_pdf(tmp_path / "empty.pdf", tmp_path / "out", FakeConverter([]))
    assert tables == []
    summary = json.loads((tmp_path / "out" / "empty" / "summary.json").read_text(encoding="utf-8"))
    assert summary["n_tables"] == 0
    assert "0 tables found" in summary["warning"]


def test_locked_csv_does_not_crash(tmp_path, monkeypatch, capsys):
    def boom(self, *a, **k):
        raise PermissionError("locked")

    monkeypatch.setattr(pd.DataFrame, "to_csv", boom)
    conv = FakeConverter([FakeTable(1, [["A", "5", "5"]])])
    tables = engine.convert_pdf(tmp_path / "r.pdf", tmp_path / "out", conv)
    assert len(tables) == 1  # JSON still written
    assert (tmp_path / "out" / "r" / "tables" / "r_p1_t1.json").exists()
    assert "WARNING" in capsys.readouterr().out


def test_compare_report_counts(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    for name in ("a.pdf", "b.pdf"):
        (samples / name).write_bytes(b"%PDF")
    d, b = tmp_path / "d", tmp_path / "b"
    (d / "a" / "tables").mkdir(parents=True)
    (d / "a" / "tables" / "a_p1_t1.json").write_text("{}")
    (d / "b" / "tables").mkdir(parents=True)          # processed, 0 tables
    (b / "a" / "tables").mkdir(parents=True)
    (b / "a" / "tables" / "a_p1_t1.json").write_text("{}")
    assert count_tables(d, "a") == 1
    assert count_tables(d, "b") == 0
    assert count_tables(b, "b") is None
    report = build_report(samples, d, b)
    assert "| `a.pdf` | 1 | 1 |" in report
    assert "| `b.pdf` | 0 | not run |" in report


def test_export_error_in_one_file_does_not_abort(tmp_path, monkeypatch):
    """An exception while writing outputs becomes a 'failed' summary instead of crashing the batch."""
    class BrokenDoc(FakeDoc):
        def export_to_markdown(self):
            raise RuntimeError("boom")

    class BrokenConverter(FakeConverter):
        def convert(self, path):
            return SimpleNamespace(document=BrokenDoc([FakeTable(1, [["A", "1", "1"]])]))

    summary = engine.process_file(tmp_path / "x.pdf", tmp_path / "out", ["fast"], lambda m: BrokenConverter([]))
    assert summary["status"] == "failed" and "export failed" in summary["error"]
