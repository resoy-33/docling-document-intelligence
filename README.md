# Layout-Aware Document Intelligence with IBM Docling

Project 20 (ISG Tunis, AI Engineering & Software Architecture). A pipeline that turns complex
PDF / DOCX / scanned documents into **verified tables**, lets you inspect the layout boxes, and
answers questions **only** from tables that passed deterministic checksum checks.

```mermaid
flowchart LR
  A[PDF / DOCX / image] --> B[Docling: layout model + TableFormer + OCR fallback]
  B --> C[DoclingDocument JSON + Markdown]
  C --> D[Tables as contract JSON / CSV / XLSX]
  D --> E[Harness: row / column checksums]
  E -->|PASS| F[Chunking + grounded Q&A]
  E -->|FLAGGED| G[Refusal with reason]
  C --> H[Inspector: boxes + reading order]
```

## Folder map

| Folder / file | Role |
|---|---|
| `engine/` | `convert.py` Docling pipeline + retry cascade (fast → accurate → OCR); `contract.py` number cleaning; `boxes.py` layout boxes and reading order; `export.py` CSV / JSON / Markdown / XLSX |
| `harness/` | checksum validator (Pydantic v2): row sums, column sums, empty cells, ragged rows |
| `inspector/` | Streamlit inspector (`app.py`, `overlay.py`): upload + convert, page with layout boxes, tables with PASS / FLAGGED, downloads, Q&A |
| `api/`, `qa/` | FastAPI service, chunking (HybridChunker, Markdown fallback), grounded Q&A with refusal |
| `automation/` | watch-folder: file dropped in `inbox/` → API → verdict → answer or refusal |
| `baseline/` | pdfplumber baseline and comparison report (for the comparison matrix) |
| `samples/`, `fixtures/` | sample documents (generated PDFs, a real invoice, its scanned version as PDF and JPEG, an annual report, the Docling paper) and 5 hand-written tables |
| `demo/` | **hand-written** test data for the API and Q&A tests (not Docling output) |
| `tests/` | pytest suite (`test_real_docling.py` runs the real models end to end; skipped without Docling) |
| `compare_digital_vs_scan.py` | one-off script for the slides: same invoice, digital PDF vs scanned PDF (full-page OCR) |

## Install (Windows)

Needs Python 3.10+ (3.12 recommended). Docling downloads about 5 GB of models on the first conversion.

```powershell
setup.bat full     # real Docling  (or: setup.bat   for the light install without Docling)
```

Manual: `py -m venv .venv`, `.venv\Scripts\Activate.ps1` (PowerShell, not `activate.bat`),
`pip install -r requirements.txt`.

## Run

| Goal | Command |
|---|---|
| Tests | `run_tests.bat` or `python -m pytest -q` |
| Convert documents | `python -m engine.convert samples --out output` (options: `--accurate`, `--ocr`, `--no-fallback`) |
| Validate tables | `python -m harness.validate output` |
| Baseline + comparison | `run_all.bat` (engine → harness → pdfplumber → harness → report) |
| Inspector | `run_inspector.bat`, then upload a PDF / DOCX / image in the sidebar (or use documents already in `output/`) |
| API | `run_api.bat` (real output) or `run_api.bat demo` (no Docling); Swagger at http://127.0.0.1:8000/docs |
| Watch-folder demo | `run_api.bat` (not `demo` mode, which would write into `demo\docs`), then `run_watch.bat "What is the total?"`, then copy a file into `automation\inbox\` |

Python API:

```python
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat

opts = PdfPipelineOptions(); opts.do_table_structure = True
conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
doc = conv.convert("report.pdf").document          # DoclingDocument
df = doc.tables[0].export_to_dataframe(doc=doc)     # pandas DataFrame
```

## Behaviour

| Situation | What happens |
|---|---|
| Unreadable file (corrupt, protected) or export error | file marked `failed`, batch continues, exit code 2 |
| PDF with 0 usable tables | retries fast → accurate → OCR + accurate; if still 0: `no_tables` + warning |
| Scanned PDF (no text layer) | without OCR Docling finds empty table outlines; they do not count, so the cascade reaches OCR automatically |
| Scanned image (PNG / JPG / TIFF) | same `PdfPipelineOptions` as PDFs, OCR always on: ocr+fast → ocr+accurate |
| Numbers like `1 234,56`, `1.234,56`, `(120)`, `$40` | converted to numbers; `12%` and `5 TND` stay text; `1,500` = 1500 |
| Merged cells | flattened to rows/columns (multi-level headers joined) |
| Table fails a checksum | `FLAGGED`; Q&A refuses and returns the reason |
| 1-column table holding a whole text block | `FLAGGED` (`MERGED_LAYOUT`); a normal 1-column list passes with a warning |

`sample_wrong_total_long_title.pdf` is kept on purpose: it is a PDF where Docling finds 0 tables,
used to show the failure path. Docling-dependent paths (real conversion, HybridChunker reload,
`--vlm`) need a machine with Docling installed; most tests use fakes, and the tests that run the
real models (`tests/test_real_docling.py` and 2 tests in `test_robustness.py`) are skipped without Docling.

Known limits (documented, not hidden):
- Invoice summary blocks (Sub Total / Tax / Total / Balance) have no header row, so Docling uses the
  first data row as header and the column-sum rule flags the table (`COLUMN_TOTAL_MISMATCH`). This is
  the safe direction: the table is refused, never used for a wrong answer.
- On `scan_invoice.jpeg` the layout model marks most of the page as one table: the result is messy and
  is flagged by the harness. The scanned **PDF** of the same invoice gives clean tables with OCR.

## API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /convert` | upload a file (or send a server-side `path`) |
| `POST /convert/path` | JSON `{"path": "..."}` (used by the watch-folder) |
| `GET /tables/{id}` | one table with its verdict: `{table, verdict, usable}` |
| `POST /ask` | `{"question", "doc_id"}` → grounded answer with citations, or `refused: true` |
| `GET /health`, `/documents`, `/tables`, `POST /validate`, `POST /reload` | status and maintenance |

More detail: [`api/README.md`](api/README.md), [`qa/README.md`](qa/README.md),
[`harness/README.md`](harness/README.md), [`inspector/README.md`](inspector/README.md),
[`automation/README.md`](automation/README.md) (step-by-step watch-folder guide).
Presentation guides: [`docs/MEMBER1_SLIDES_GUIDE.md`](docs/MEMBER1_SLIDES_GUIDE.md),
[`docs/MEMBER3_SLIDES_GUIDE.md`](docs/MEMBER3_SLIDES_GUIDE.md).
Reference: https://github.com/docling-project/docling
