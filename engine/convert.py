"""Core engine: documents -> Docling -> tables in the team's JSON contract.

Usage (from the project root, with the venv active):

    python -m engine.convert samples                      # every supported file in the folder
    python -m engine.convert report.docx --out output     # one file (PDF, Word, Excel, ...)
    python -m engine.convert samples --accurate --ocr     # start with these options
    python -m engine.convert samples --vlm                # also allow the AI vision fallback (slow)
    python -m engine.convert samples --no-fallback        # one attempt per file, no retries

Inputs: PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), HTML, and images (.png .jpg .tif).
Old binary formats (.doc, .ppt, .xls) are NOT handled by this script.

For every file it writes, under output/<doc_id>/ :
    <doc_id>.md             Markdown export of the whole document
    <doc_id>.docling.json   full DoclingDocument as JSON
    tables/<table_id>.json  one file per table, in the TEAM CONTRACT format
    tables/<table_id>.csv   same table as CSV (handy for screenshots)
    summary.json            status, tables found, attempts made, warnings or the error
and one output/run_report.json for the whole run.

Status of a file: "ok" (>= 1 table), "no_tables" (read fine, 0 tables), "failed" (could not be read).
Neither "no_tables" nor "failed" stops the run. Downstream code (the harness) must treat
"0 tables where one is expected" and "failed" as FAILURES, never as success.

Retry cascade for PDFs with 0 usable tables: fast -> accurate -> OCR + accurate -> (optional) AI vision model.
"Usable" means the table has at least one cell: a scanned page read WITHOUT OCR gives empty table
outlines, so those do not stop the cascade. Images (scans/photos) always use OCR: ocr+fast -> ocr+accurate.
Whatever any attempt extracts is still plain data: it must pass the harness checksums like everything else.
"""
from __future__ import annotations

import os

# Harmless Windows warning about symlinks in the Hugging Face cache: hide it.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Callable  # noqa: E402

import pandas as pd  # noqa: E402

from engine.contract import dataframe_to_contract  # noqa: E402

ZERO_TABLES_WARNING = (
    "0 tables found. If this document should contain a table, treat this as a FAILURE "
    "(Docling's layout model can miss or mislabel a table)."
)

EMPTY_TABLES_WARNING = (
    "Tables were detected but none contains any text (a scanned page read without OCR?). "
    "Try again with --ocr."
)

PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
OTHER_SUFFIXES = {".docx", ".pptx", ".xlsx", ".html", ".htm"} | IMAGE_SUFFIXES
SUPPORTED_SUFFIXES = PDF_SUFFIXES | OTHER_SUFFIXES


# ----------------------------------------------------------------- converters
def build_converter(accurate: bool = False, ocr: bool = False):
    """Docling converter for PDFs and images. Table structure (TableFormer) is always on.

    Images (scanned pages, photos) go through the same page pipeline as PDFs, so they get
    the same PdfPipelineOptions.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.do_ocr = ocr
    opts.table_structure_options.mode = (
        TableFormerMode.ACCURATE if accurate else TableFormerMode.FAST
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts),
        }
    )


def build_vlm_converter():
    """Docling's AI vision-language-model pipeline (reads the page image). Slow, big download.

    Not tested by the author: the first run downloads a model, ideally use a machine with a GPU.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import VlmPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=VlmPipeline, pipeline_options=VlmPipelineOptions()
            )
        }
    )


def make_converter(mode: str):
    """mode: 'default' (Word, PowerPoint, Excel, HTML), 'fast', 'accurate', 'ocr+fast',
    'ocr+accurate' or 'vlm'."""
    if mode == "default":
        from docling.document_converter import DocumentConverter

        return DocumentConverter()
    if mode == "vlm":
        return build_vlm_converter()
    return build_converter(accurate=mode.endswith("accurate"), ocr=mode.startswith("ocr"))


def plan_attempts(path: Path, accurate: bool, ocr: bool, vlm: bool, fallback: bool) -> list[str]:
    """The ordered list of converter modes to try for one file."""
    suffix = path.suffix.lower()
    is_image = suffix in IMAGE_SUFFIXES
    if is_image:
        ocr = True  # a picture has no text layer: OCR is always needed
    elif suffix not in PDF_SUFFIXES:
        return ["default"]  # Word / PowerPoint / Excel / HTML: one attempt
    first = ("ocr+" if ocr else "") + ("accurate" if accurate else "fast")
    plan = [first]
    if fallback:
        for mode in ("accurate", "ocr+accurate"):
            if is_image and not mode.startswith("ocr"):
                continue
            if mode not in plan:
                plan.append(mode)
    if vlm and not is_image:  # the VLM converter is configured for PDFs only
        plan.append("vlm")
    return plan


# ------------------------------------------------------------------- tables
def table_dataframe(table, doc) -> pd.DataFrame:
    """One Docling table as a pandas DataFrame."""
    try:
        return table.export_to_dataframe(doc=doc)
    except TypeError:  # older docling versions have no `doc` argument
        return table.export_to_dataframe()


def count_usable_tables(doc) -> int:
    """Tables with at least one column. A scanned page converted without OCR gives
    empty table outlines (0 columns): they must not count as "tables found"."""
    return sum(1 for table in doc.tables if len(table_dataframe(table, doc).columns) > 0)


def extract_tables(doc, doc_id: str) -> list[dict]:
    """Walk doc.tables and convert each one to the contract format."""
    per_page_counter: dict[int, int] = {}
    tables = []
    for table in doc.tables:
        page = table.prov[0].page_no if table.prov else 0
        per_page_counter[page] = per_page_counter.get(page, 0) + 1
        df = table_dataframe(table, doc)
        tables.append(dataframe_to_contract(df, doc_id, page, per_page_counter[page]))
    return tables


def write_csv_safe(df: pd.DataFrame, path: Path) -> bool:
    """Write a CSV; if the file is locked (open in Excel on Windows) warn and go on."""
    try:
        df.to_csv(path, index=False)
        return True
    except PermissionError:
        print(f"  WARNING: could not write {path} (is it open in Excel?). Skipped this CSV.")
        return False


def doc_id_for(path: Path) -> str:
    """report.pdf -> 'report' (unchanged), report.docx -> 'report_docx' (no name clash)."""
    path = Path(path)
    if path.suffix.lower() in PDF_SUFFIXES:
        return path.stem
    return f"{path.stem}_{path.suffix.lower().lstrip('.')}"


# ------------------------------------------------------------------- writing
def clear_previous_outputs(target: Path, doc_id: str) -> None:
    """Delete the files of an earlier conversion of the SAME document.

    Without this, converting a file again (other options, or a failure) would leave old
    table files next to the new summary, and they would still be shown and validated.
    """
    old_files = [target / f"{doc_id}.md", target / f"{doc_id}.docling.json",
                 *target.glob("tables/*.json"), *target.glob("tables/*.csv")]
    for path in old_files:
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            print(f"  WARNING: could not delete the old file {path} (is it open in another program?)")


def write_outputs(doc, source: Path, out_dir: Path, seconds: float, extra: dict | None = None):
    """Write md / json / tables / summary for one converted document. Returns (tables, summary)."""
    doc_id = doc_id_for(source)
    target = Path(out_dir) / doc_id
    clear_previous_outputs(target, doc_id)
    (target / "tables").mkdir(parents=True, exist_ok=True)

    (target / f"{doc_id}.md").write_text(doc.export_to_markdown(), encoding="utf-8")
    (target / f"{doc_id}.docling.json").write_text(
        json.dumps(doc.export_to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    tables = extract_tables(doc, doc_id)
    for t in tables:
        (target / "tables" / f"{t['table_id']}.json").write_text(
            json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_csv_safe(
            pd.DataFrame(t["rows"], columns=t["columns"]),
            target / "tables" / f"{t['table_id']}.csv",
        )

    summary = {
        "doc_id": doc_id,
        "source": str(source),
        "status": "ok" if tables else "no_tables",
        "seconds": round(seconds, 2),
        "n_tables": len(tables),
        "table_ids": [t["table_id"] for t in tables],
    }
    if not tables:
        summary["warning"] = ZERO_TABLES_WARNING
    elif not any(t["columns"] for t in tables):
        summary["warning"] = EMPTY_TABLES_WARNING
    summary.update(extra or {})
    (target / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return tables, summary


def convert_pdf(pdf_path: Path, out_dir: Path, converter) -> list[dict]:
    """One attempt with one given converter (kept for simple use and for tests)."""
    pdf_path = Path(pdf_path)
    start = time.perf_counter()
    result = converter.convert(pdf_path)
    seconds = time.perf_counter() - start
    tables, _ = write_outputs(result.document, pdf_path, out_dir, seconds)
    return tables


def process_file(
    path: Path,
    out_dir: Path,
    plan: list[str],
    get_converter: Callable[[str], object],
) -> dict:
    """Run the attempts in `plan` until one finds a table. Never raises: returns the summary dict.

    Keeps the first attempt that found a usable table (with cells); otherwise the last attempt
    that could read the file.
    """
    path = Path(path)
    attempts: list[dict] = []
    best = None  # (doc, seconds, mode)
    for mode in plan:
        start = time.perf_counter()
        try:
            doc = get_converter(mode).convert(path).document
            seconds = time.perf_counter() - start
            usable = count_usable_tables(doc)
            attempts.append({"mode": mode, "n_tables": len(doc.tables),
                             "n_usable": usable, "error": None})
            best = (doc, seconds, mode)
            if usable > 0:
                break
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
            attempts.append({"mode": mode, "n_tables": None, "error": f"{type(exc).__name__}: {exc}"})

    if best is None:  # no attempt could read the file
        target = Path(out_dir) / doc_id_for(path)
        clear_previous_outputs(target, doc_id_for(path))
        target.mkdir(parents=True, exist_ok=True)
        summary = {
            "doc_id": doc_id_for(path),
            "source": str(path),
            "status": "failed",
            "n_tables": 0,
            "table_ids": [],
            "attempts": attempts,
            "error": attempts[-1]["error"] if attempts else "no attempt made",
        }
        (target / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    doc, seconds, mode = best
    try:
        _, summary = write_outputs(doc, path, out_dir, seconds, {"mode": mode, "attempts": attempts})
    except Exception as exc:  # noqa: BLE001 - an export error must not abort the whole batch
        target = Path(out_dir) / doc_id_for(path)
        clear_previous_outputs(target, doc_id_for(path))  # no half-written results
        target.mkdir(parents=True, exist_ok=True)
        summary = {
            "doc_id": doc_id_for(path),
            "source": str(path),
            "status": "failed",
            "n_tables": 0,
            "table_ids": [],
            "attempts": attempts,
            "error": f"export failed: {type(exc).__name__}: {exc}",
        }
        (target / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# ------------------------------------------------------------------------ CLI
def find_files(source: Path) -> list[Path]:
    if source.is_dir():
        return sorted(p for p in source.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
    return [source]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Documents -> Docling -> contract JSON tables")
    ap.add_argument("source", help="a file (PDF, docx, pptx, xlsx, html, image) or a folder")
    ap.add_argument("--out", default="output", help="output folder (default: output)")
    ap.add_argument("--accurate", action="store_true", help="start with TableFormer ACCURATE mode")
    ap.add_argument("--ocr", action="store_true", help="start with OCR on (scanned PDFs)")
    ap.add_argument("--vlm", action="store_true", help="add the AI vision-model fallback (slow, untested)")
    ap.add_argument("--no-fallback", action="store_true", help="one attempt per file, no retries")
    args = ap.parse_args(argv)

    src = Path(args.source)
    if not src.exists():
        raise SystemExit(f"Not found: {src}")
    files = find_files(src)
    if not files:
        raise SystemExit(f"No supported file in {src} (supported: {sorted(SUPPORTED_SUFFIXES)})")

    cache: dict[str, object] = {}

    def get_converter(mode: str):
        if mode not in cache:
            cache[mode] = make_converter(mode)
        return cache[mode]

    out_dir = Path(args.out)
    report = []
    for path in files:
        plan = plan_attempts(path, args.accurate, args.ocr, args.vlm, not args.no_fallback)
        summary = process_file(path, out_dir, plan, get_converter)
        report.append(summary)
        tag = {"ok": "", "no_tables": "  <- 0 tables", "failed": "  <- FAILED"}[summary["status"]]
        print(f"{path.name}: {summary['n_tables']} table(s) [{summary['status']}] -> "
              f"{out_dir / summary['doc_id']}{tag}")
        if summary["status"] == "failed":
            print(f"  ERROR: {summary['error']}")
        elif summary.get("warning"):
            print(f"  WARNING: {summary['warning']}")
        tried = summary.get("attempts", [])
        if len(tried) > 1:  # e.g. "fast=0 usable/3, ocr+accurate=3 usable/3"
            print("  attempts: " + ", ".join(
                f"{a['mode']}=error" if a["error"] else f"{a['mode']}={a['n_usable']} usable/{a['n_tables']}"
                for a in tried))

    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {s: sum(1 for r in report if r["status"] == s) for s in ("ok", "no_tables", "failed")}
    (out_dir / "run_report.json").write_text(
        json.dumps({"counts": counts, "files": report}, indent=2), encoding="utf-8"
    )
    print(f"\nSummary: {counts['ok']} ok, {counts['no_tables']} with 0 tables, {counts['failed']} failed "
          f"(details: {out_dir / 'run_report.json'})")
    return 2 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
