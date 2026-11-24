"""Bounding-box inspector (Streamlit).

    streamlit run inspector/app.py        (or run_inspector.bat)

Sidebar: upload a PDF / DOCX / scanned image and convert it with Docling, or pick a document
         already converted by `python -m engine.convert` (folder `output/`, or DOCLING_OUTPUT_DIR).
Main:    a small dashboard (status, tables, PASS / FLAGGED), then five tabs:
           1. Page & layout boxes   rendered page with Docling's boxes, numbered in reading order
           2. Tables & validation   each table, its checksum verdict explained, downloads
           3. Markdown              the whole document exported to Markdown by Docling
           4. Ask a question        grounded Q&A: answers only from tables that PASSED
           5. Conversion details    attempts of the retry cascade, warnings, errors
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from engine.boxes import boxes_for_page, label_counts, load_boxes, page_sizes  # noqa: E402
from engine.convert import SUPPORTED_SUFFIXES  # noqa: E402
from engine.export import (  # noqa: E402
    table_to_csv_bytes, table_to_dataframe, table_to_json_bytes, table_to_markdown,
    table_to_markdown_bytes, tables_to_xlsx_bytes,
)
from harness.models import ValidationReport  # noqa: E402
from harness.validate import validate_directory, validate_file  # noqa: E402
from inspector.overlay import PREVIEW_SUFFIXES, color_for, draw_boxes, render_page  # noqa: E402

SCALE = 1.5
UPLOAD_DIR = ROOT / "uploads"

# Plain-language meaning of each harness failure code, shown under a FLAGGED table.
EXPLAIN = {
    "INVALID_FORMAT": "The table file is not in the expected format (for example a table without columns).",
    "COLUMN_COUNT": "Some rows have more or fewer cells than there are columns.",
    "EMPTY_CELL": "Some cells are empty: a value may have been lost during extraction.",
    "NON_NUMERIC": "A numeric column contains text (often a misread number).",
    "ROW_TOTAL_MISMATCH": "The values of a row do not add up to its Total column.",
    "COLUMN_TOTAL_MISMATCH": "The values of a column do not add up to the Total row.",
    "NO_TOTALS": "The table has no Total row or column, so nothing could be verified.",
    "MERGED_LAYOUT": "A single cell holds a long block of text: this is not a real table.",
}


# ------------------------------------------------------------------ helpers
def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def display_frame(table: dict) -> pd.DataFrame:
    """DataFrame for st.dataframe (display only, the downloads keep the real values).

    Streamlit needs unique headers, and a column mixing text and numbers (common in OCR
    output) is shown as text.
    """
    df = table_to_dataframe(table)
    seen: dict[str, int] = {}
    names = []
    for name in (str(c) or "(empty)" for c in df.columns):
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    df.columns = names
    for name in names:
        if df[name].map(lambda v: isinstance(v, str)).any():
            df[name] = df[name].map(lambda v: "" if v is None else str(v))
    return df


def convert_upload(upload, root: Path, accurate: bool, ocr: bool) -> None:
    """Save the uploaded file in uploads/ and convert it. Runs ONLY when the button is clicked."""
    from api.convert import convert_file, docling_available

    if not docling_available():
        st.session_state["message"] = (
            "error", "Docling is not installed in this environment (run `setup.bat full`).")
        return
    try:
        UPLOAD_DIR.mkdir(exist_ok=True)
        source = UPLOAD_DIR / Path(upload.name).name
        source.write_bytes(upload.getbuffer())
        with st.spinner(f"Docling is converting {upload.name} (the first run downloads the models)..."):
            summary = convert_file(source, root, accurate=accurate, ocr=ocr)
    except Exception as exc:  # noqa: BLE001 - show the reason instead of a stack trace
        st.session_state["message"] = ("error", f"Conversion failed: {type(exc).__name__}: {exc}")
        return

    st.session_state["doc"] = summary["doc_id"]  # select the new document
    if summary["status"] == "ok":
        st.session_state["message"] = (
            "success", f"{upload.name}: {summary['n_tables']} table(s) extracted "
                       f"(mode {summary.get('mode', '?')}, {summary.get('seconds', '?')} s).")
    elif summary["status"] == "no_tables":
        st.session_state["message"] = ("warning", f"{upload.name}: converted, but 0 tables found.")
    else:
        st.session_state["message"] = ("error", f"{upload.name}: Docling could not read the file. "
                                                f"{summary.get('error', '')}")


def verdict_text(report: ValidationReport) -> str:
    return "✅ PASS" if report.passed else "❌ FLAGGED"


# ------------------------------------------------------------------ sidebar
st.set_page_config(page_title="Docling Document Inspector", page_icon="📄", layout="wide")

with st.sidebar:
    st.header("1. Convert a document")
    upload = st.file_uploader(
        "PDF, Word (DOCX) or scanned image (PNG, JPG, TIFF). PPTX, XLSX and HTML also work.",
        type=sorted(s.lstrip(".") for s in SUPPORTED_SUFFIXES),
    )
    ocr = st.checkbox("Force OCR (scanned documents)", help="Images always use OCR. For a scanned "
                      "PDF, OCR is also tried automatically when no readable table is found.")
    accurate = st.checkbox("Accurate table mode (slower)", help="TableFormer ACCURATE instead of FAST.")
    root = Path(os.getenv("DOCLING_OUTPUT_DIR", "output"))
    with st.expander("Settings"):
        root = Path(st.text_input("Output folder", str(root)))
    if st.button("Convert with Docling", type="primary", disabled=upload is None):
        convert_upload(upload, root, accurate, ocr)
    if "message" in st.session_state:
        kind, text = st.session_state["message"]
        getattr(st, kind)(text)  # st.success / st.warning / st.error

    st.header("2. Choose a document")
    docs = sorted(p.parent.name for p in root.glob("*/summary.json")) if root.exists() else []
    if st.session_state.get("doc") not in docs:
        st.session_state.pop("doc", None)
    doc_id = st.selectbox("Document", docs, key="doc") if docs else None

st.title("📄 Docling Document Inspector")
st.caption("Layout-aware document intelligence with IBM Docling: page layout boxes, reconstructed "
           "tables and checksum validation. Only tables that PASS are used to answer questions.")

if doc_id is None:
    st.info(f"No converted document in `{root}` yet. Upload a file in the sidebar and click "
            "**Convert with Docling**, or run `python -m engine.convert samples --out output`.")
    st.stop()

# ------------------------------------------------------------------ data of the selected document
folder = root / doc_id
summary = read_json(folder / "summary.json")
table_files = sorted((folder / "tables").glob("*.json"))
tables = [read_json(path) for path in table_files]
reports = [validate_file(path) for path in table_files]  # never raises: a bad file is FLAGGED
docling_json = folder / f"{doc_id}.docling.json"
docling_doc = read_json(docling_json) if docling_json.exists() else {}

# ------------------------------------------------------------------ dashboard
n_pass = sum(r.passed for r in reports)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Status", summary.get("status", "unknown"))
c2.metric("Pages", len(docling_doc.get("pages") or {}) or "-")
c3.metric("Tables", len(tables))
c4.metric("✅ Passed", n_pass)
c5.metric("❌ Flagged", len(reports) - n_pass)

if summary.get("status") == "failed":
    st.error(f"Docling could not read this document: {summary.get('error', 'unknown error')}")
elif summary.get("warning"):
    st.warning(summary["warning"])

with st.expander("How to read the results"):
    st.markdown(
        "- **Layout boxes**: every paragraph, heading, table or figure Docling found, with its "
        "number in the recovered reading order.\n"
        "- **✅ PASS**: rows are complete and, when the table has a *Total* row or column, the "
        "totals were recomputed and match.\n"
        "- **❌ FLAGGED**: at least one check failed (wrong total, empty cell, text in a number "
        "column, broken rows...). A flagged table is never used to answer a question.\n"
        "- **0 tables** or a **failed** conversion count as failures, not as success."
    )

with st.expander("All documents in this folder"):
    batch = validate_directory(root)
    issues = {i.doc_id: i.code.value for i in batch.doc_issues}
    st.dataframe(pd.DataFrame([{
        "document": d,
        "tables": sum(r.doc_id == d for r in batch.reports),
        "passed": sum(r.doc_id == d and r.passed for r in batch.reports),
        "flagged": sum(r.doc_id == d and not r.passed for r in batch.reports),
        "issue": issues.get(d, ""),
    } for d in batch.doc_ids]), hide_index=True)

tab_page, tab_tables, tab_md, tab_ask, tab_details = st.tabs(
    ["Page & layout boxes", "Tables & validation", "Markdown", "Ask a question", "Conversion details"])

# ------------------------------------------------------------------ tab 1: page + boxes
with tab_page:
    source = Path(summary.get("source", ""))
    if not docling_doc:
        st.info("No Docling JSON for this document (failed conversion or hand-written demo data): "
                "there are no boxes to show.")
    elif source.suffix.lower() not in PREVIEW_SUFFIXES:
        st.info(f"`{source.suffix}` files have no page image: Docling reads their structure "
                "directly, so there are no boxes to draw. The tables are in the next tab.")
    elif not source.exists():
        st.warning(f"The original file was not found at `{source}`, so the page cannot be drawn. "
                   "Start the app from the project folder, or convert the file again.")
    else:
        boxes = load_boxes(docling_doc)
        pages = sorted({b.page for b in boxes})
        if not pages:
            st.info("Docling found no layout items in this document.")
        else:
            o1, o2, o3 = st.columns([1, 3, 1])
            page = o1.selectbox("Page", pages)
            counts = label_counts(boxes_for_page(boxes, page))
            labels = set(o2.multiselect("Layout labels shown", list(counts), default=list(counts)))
            show_order = o3.checkbox("Number boxes in reading order", True)
            page_boxes = boxes_for_page(boxes, page, labels)

            left, right = st.columns([3, 2])
            with left:
                try:
                    image = render_page(source, page, SCALE, page_sizes(docling_doc).get(page))
                    st.image(draw_boxes(image, page_boxes, SCALE, show_order), width="stretch",
                             caption=f"{doc_id} - page {page}: {len(page_boxes)} boxes")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not render page {page} of `{source.name}`: {exc}")
            with right:
                st.markdown("**Legend** " + " ".join(
                    f"<span style='color:{color_for(k)}'>■ {k} ({v})</span>" for k, v in counts.items()),
                    unsafe_allow_html=True)
                page_tables = [(t, r) for t, r in zip(tables, reports) if t.get("page") == page]
                for table, report in page_tables:
                    st.markdown(f"Table **{report.table_id}**: {verdict_text(report)}")
                st.markdown("**Layout items in reading order**")
                st.dataframe(pd.DataFrame([{
                    "#": b.order + 1 if b.order < 10**6 else None,
                    "label": b.label,
                    "text": b.text[:120],
                } for b in page_boxes]), hide_index=True, height=420)

# ------------------------------------------------------------------ tab 2: tables + verdicts
with tab_tables:
    if not tables:
        st.info("No table was extracted from this document.")
    else:
        valid_tables = [t for t in tables if t.get("columns") is not None and t.get("rows") is not None]
        st.download_button("Download all tables (Excel)", tables_to_xlsx_bytes(valid_tables),
                           f"{doc_id}_tables.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    for table, report in zip(tables, reports):
        with st.container(border=True):
            n_rows, n_cols = len(table.get("rows") or []), len(table.get("columns") or [])
            st.markdown(f"#### {report.table_id} — {verdict_text(report)}")
            st.caption(f"page {table.get('page', '?')} · {n_rows} rows × {n_cols} columns")
            if report.passed and report.verifiable:
                st.success("PASS: the totals were recomputed and match the table.")
            elif report.passed:
                st.info("PASS (structure only): the rows and cells are complete, but there is no "
                        "Total row or column, so the numbers could not be cross-checked.")
            else:
                st.error("FLAGGED: this table failed validation and will not be used to answer "
                         "questions.\n\n" + "\n".join(
                             f"- **{f.code.value}**: {EXPLAIN.get(f.code.value, '')} *{f.message}*"
                             for f in report.failures))
            for warning in report.warnings:
                st.warning(f"Warning: {warning}")
            if not n_cols:
                st.caption("This table has no columns, nothing to show.")
                continue
            st.dataframe(display_frame(table), hide_index=True)
            d1, d2, d3, _ = st.columns([1, 1, 1, 3])
            tid = report.table_id
            d1.download_button("CSV", table_to_csv_bytes(table), f"{tid}.csv", "text/csv", key=f"csv_{tid}")
            d2.download_button("JSON", table_to_json_bytes(table), f"{tid}.json", "application/json",
                               key=f"json_{tid}")
            d3.download_button("Markdown", table_to_markdown_bytes(table), f"{tid}.md", "text/markdown",
                               key=f"md_{tid}")
            with st.expander("Markdown preview"):
                st.code(table_to_markdown(table), language="markdown")

# ------------------------------------------------------------------ tab 3: Markdown of the document
with tab_md:
    md_path = folder / f"{doc_id}.md"
    if not md_path.exists():
        st.info("No Markdown export for this document.")
    else:
        markdown = md_path.read_text(encoding="utf-8")
        st.download_button("Download document (Markdown)", markdown.encode("utf-8"), md_path.name,
                           "text/markdown")
        view = st.radio("View", ["Rendered", "Markdown source"], horizontal=True)
        if view == "Rendered":
            st.markdown(markdown)
        else:
            st.code(markdown, language="markdown")

# ------------------------------------------------------------------ tab 4: grounded Q&A
with tab_ask:
    st.caption("Answers are computed only from tables of this document that PASSED validation. "
               "If the matching table was FLAGGED, the system refuses and explains why.")
    question = st.text_input("Question", placeholder="e.g. What is the total?")
    if st.button("Ask", disabled=not question.strip()):
        from qa.service import QAService

        with st.spinner("Searching the validated tables..."):
            answer = QAService(root, prefer_hybrid=False).ask(question, doc_id=doc_id)
        if answer.refused:
            st.error(f"REFUSED: {answer.reason}")
        else:
            st.success(answer.answer)
        for citation in answer.citations:
            st.caption(f"Source: table {citation.table_id}, page {citation.page}"
                       + (f", row '{citation.row_label}'" if citation.row_label else "")
                       + (f", column '{citation.column}'" if citation.column else ""))
        for warning in answer.warnings:
            st.warning(warning)

# ------------------------------------------------------------------ tab 5: conversion details
with tab_details:
    st.markdown(f"**Source file:** `{summary.get('source', '?')}`  \n"
                f"**Mode used:** `{summary.get('mode', '?')}`  \n"
                f"**Time:** {summary.get('seconds', '?')} s")
    attempts = summary.get("attempts") or []
    if attempts:
        st.markdown("**Retry cascade** (fast → accurate → OCR + accurate, stops at the first "
                    "attempt that finds a usable table)")
        st.dataframe(pd.DataFrame(attempts), hide_index=True)
    with st.expander("summary.json"):
        st.json(summary)
