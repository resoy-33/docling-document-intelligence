"""Boxes, reading order, Excel export, overlay and the Streamlit app (no Docling models needed)."""
import io
import json
from pathlib import Path

import openpyxl
import pytest

from engine.boxes import boxes_for_page, label_counts, load_boxes, reading_order
from engine.export import table_to_csv_bytes, tables_to_xlsx_bytes

ROOT = Path(__file__).parent.parent

DOC = {
    "pages": {"1": {"page_no": 1, "size": {"width": 600, "height": 800}}},
    "body": {"children": [{"$ref": "#/texts/1"}, {"$ref": "#/groups/0"}, {"$ref": "#/tables/0"}]},
    "groups": [{"children": [{"$ref": "#/texts/0"}]}],
    "texts": [
        {"label": "text", "text": "second in reading order",
         "prov": [{"page_no": 1, "bbox": {"l": 50, "t": 700, "r": 300, "b": 650, "coord_origin": "BOTTOMLEFT"}}]},
        {"label": "section_header", "text": "Title",
         "prov": [{"page_no": 1, "bbox": {"l": 50, "t": 100, "r": 300, "b": 130, "coord_origin": "TOPLEFT"}}]},
    ],
    "tables": [{"label": "table", "data": {"num_rows": 3, "num_cols": 2},
                "prov": [{"page_no": 1, "bbox": {"l": 50, "t": 400, "r": 500, "b": 300, "coord_origin": "BOTTOMLEFT"}}]}],
}

TABLE = {"doc_id": "d", "table_id": "d_p1_t1", "page": 1, "columns": ["Item", "Q1"],
         "rows": [["A", 10], ["B", 5], ["Total", 15]]}


def test_reading_order_follows_body_tree():
    assert reading_order(DOC) == {"#/texts/1": 0, "#/texts/0": 1, "#/tables/0": 2}


def test_bottomleft_is_flipped_to_topleft():
    boxes = {b.ref: b for b in load_boxes(DOC)}
    text = boxes["#/texts/0"]  # BOTTOMLEFT t=700,b=650 on an 800-high page -> top=100, bottom=150
    assert (text.top, text.bottom) == (100, 150)
    assert boxes["#/texts/1"].top == 100  # TOPLEFT stays as is
    assert [b.label for b in load_boxes(DOC)] == ["section_header", "text", "table"]  # sorted by order


def test_page_filter_and_counts():
    boxes = load_boxes(DOC)
    assert len(boxes_for_page(boxes, 1, {"table"})) == 1
    assert boxes_for_page(boxes, 2) == []
    assert label_counts(boxes)["text"] == 1


def test_xlsx_has_one_numeric_sheet_per_table():
    other = dict(TABLE, table_id="x" * 40)  # name longer than 31 chars
    wb = openpyxl.load_workbook(io.BytesIO(tables_to_xlsx_bytes([TABLE, other])))
    assert len(wb.sheetnames) == 2 and all(len(n) <= 31 for n in wb.sheetnames)
    assert wb["d_p1_t1"]["B2"].value == 10  # stays a number, not text


def test_xlsx_and_csv_for_empty_input():
    wb = openpyxl.load_workbook(io.BytesIO(tables_to_xlsx_bytes([])))
    assert wb.sheetnames == ["no_tables"]
    assert table_to_csv_bytes(TABLE).decode("utf-8-sig").splitlines()[0] == "Item,Q1"


def test_overlay_draws_on_a_real_pdf():
    pytest.importorskip("pypdfium2")
    from inspector.overlay import draw_boxes, render_page

    image = render_page(ROOT / "samples" / "sample_simple_table.pdf", 1, scale=1.0)
    drawn = draw_boxes(image, load_boxes(DOC), 1.0)
    assert drawn.size == image.size and drawn.tobytes() != image.tobytes()


def test_streamlit_app_runs_on_a_converted_folder(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    folder = tmp_path / "out" / "sample_simple_table"
    (folder / "tables").mkdir(parents=True)
    (folder / "sample_simple_table.docling.json").write_text(json.dumps(DOC))
    (folder / "tables" / "d_p1_t1.json").write_text(json.dumps(TABLE))
    (folder / "summary.json").write_text(json.dumps(
        {"doc_id": "sample_simple_table", "status": "ok", "n_tables": 1,
         "source": str(ROOT / "samples" / "sample_simple_table.pdf")}))
    monkeypatch.setenv("DOCLING_OUTPUT_DIR", str(tmp_path / "out"))
    app = AppTest.from_file(str(ROOT / "inspector" / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert any("PASS" in m.value for m in app.markdown)


def test_markdown_export_escapes_pipes_and_line_breaks():
    from engine.export import table_to_markdown

    md = table_to_markdown({"columns": ["Item", "Q1"], "rows": [["a|b", 1.0], ["two\nlines", None]]})
    assert md.splitlines() == ["| Item | Q1 |", "| --- | --- |", "| a\\|b | 1 |", "| two lines |  |"]


def test_ragged_table_can_still_be_exported():
    """A table flagged COLUMN_COUNT must not crash the CSV / Excel downloads."""
    ragged = {"table_id": "r", "columns": ["Item", "Q1"], "rows": [["A"], ["B", 2, 99]]}
    lines = table_to_csv_bytes(ragged).decode("utf-8-sig").splitlines()
    assert lines == ["Item,Q1,extra_3", "A,,", "B,2,99"]
    assert tables_to_xlsx_bytes([ragged])


def test_render_page_of_a_scanned_image(tmp_path):
    from PIL import Image

    from inspector.overlay import render_page

    path = tmp_path / "scan.png"
    Image.new("RGB", (400, 200), "white").save(path)
    # Docling stores image pages in points (pixels * 0.75): the picture is resized to match
    assert render_page(path, 1, scale=2, page_size=(300, 150)).size == (600, 300)


def test_streamlit_app_handles_docx_without_page_image(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    folder = tmp_path / "out" / "report_docx"
    (folder / "tables").mkdir(parents=True)
    (folder / "report_docx.docling.json").write_text(json.dumps(DOC))
    (folder / "tables" / "d_p1_t1.json").write_text(json.dumps(TABLE))
    (folder / "summary.json").write_text(json.dumps(
        {"doc_id": "report_docx", "status": "ok", "n_tables": 1, "source": "report.docx"}))
    monkeypatch.setenv("DOCLING_OUTPUT_DIR", str(tmp_path / "out"))
    app = AppTest.from_file(str(ROOT / "inspector" / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert any("no page image" in info.value for info in app.info)
    assert any("PASS" in m.value for m in app.markdown)


def test_reading_order_ignores_body_and_malformed_refs():
    doc = {"body": {"children": [{"$ref": "#/body"}, {"$ref": "#/texts/0"}, {"$ref": "#/groups/9"}]},
           "texts": [{}], "groups": []}
    assert reading_order(doc) == {"#/texts/0": 0}
