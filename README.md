# Layout-Aware Document Intelligence & Table Structure Reconstruction Harness with IBM Docling

Subject #20 (DS1). Team project: a pipeline that turns complex PDFs into verified tables,
and only answers questions from tables that passed deterministic checks.

```
PDF dropped in a watch-folder / n8n webhook
  -> Docling (layout analysis + TableFormer)        [Member 1: engine/]
  -> tables as JSON in the team contract            [Member 1: engine/]
  -> checksum validation (Pydantic v2 + pytest)     [Member 2: harness/, tests/]
  -> chunking, FastAPI, grounded Q&A                [Member 3: api/, qa/]
  -> automation, packaging, demo                    [Member 4: automation/]
```

Official reference: https://github.com/docling-project/docling

---

## What is verified and what is not

| Item | Status |
|---|---|
| `engine/convert.py` on 3 sample PDFs with Docling 2.151.1 on Windows | Run by Yosr: 1 table each for `sample_simple_table`, `sample_two_column_table` and `sample_wrong_total` |
| `sample_wrong_total_long_title.pdf` | Docling found **0 tables** (normal, OCR, accurate, OCR+accurate), and the CLI labelled the table as an image. Cause not established. Kept as a real failure case |
| `pytest` suite (121 collected) | **119 passed, 2 skipped** on Windows/Python 3.12 on 2026-11-22 without Docling. The 2 skips are Member 1's Docling-only tests. |
| Word, Excel and HTML input (real Docling run, 3 files) | Worked in the author's test environment: 1 table each; number formats parsed. Not tested on your PCs |
| PDF retry cascade (fast, accurate, OCR + accurate) and the AI vision option `--vlm` | Logic tested with fake converters only. The real PDF cascade and `--vlm` have **not** been run |
| Scanned PDFs, borderless tables, merged cells, images, PowerPoint | **Not tested** |
| `setup_windows.bat`, `run_all.bat` | Written but **not tested on Windows**. If one fails, use the manual commands below |
| Table content correctness across tools | **Not measured yet**: needs Member 2's validator and harder PDFs |
| **Member 3: chunking, API, grounded Q&A** | Implemented and tested: `119 passed, 2 skipped` for the whole suite; real uvicorn server checked on `/health`, `/ask`, `/tables/{id}`, `/validate`, `/openapi.json` |
| **Member 3: HybridChunker** | Code path implemented; **not executed** because Docling was not installed on the test machine. The labelled Markdown fallback ran instead (`chunking_method` is exposed by the API) |
| **Member 3: real Docling output through the API** | **Not run here**. Documented: `python -m engine.convert samples --out output`, then `set DOCLING_OUTPUT_DIR=output` |
| **Member 3: demo corpus** | Hand-written for API/Q&A tests, **not** Docling output; stated in `demo/docs/README.md` |

---

## Member 3 quick start (API + grounded Q&A, no Docling download)

The `api/` and `qa/` folders are Member 3's part. They can be run on a light setup because
the demo output in `demo/docs/` is hand-written (clearly labelled, **not** Docling output).
This lets you test chunking, retrieval, refusal and the API before installing the 5 GB
Docling models.

```bat
cd C:\path\to\docling-document-intelligence
setup_member3.bat
run_demo_api.bat
```

`setup_member3.bat` creates `.venv`, installs `requirements-api.txt`, generates
`demo/docs/`, and runs the tests. `run_demo_api.bat` serves the API at
**http://127.0.0.1:8000** with Swagger at **http://127.0.0.1:8000/docs**.

Manual commands:

```bat
py -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements-api.txt
python demo\make_demo.py
python -m pytest -q
set DOCLING_OUTPUT_DIR=demo\docs
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Demo questions (the API returns a citation or a refusal with a reason):

| Question | Expected |
|---|---|
| `What were Laptops sales in Q1?` (`doc_id=sales_2026`) | `120`, page 1, table `sales_2026_p1_t1` |
| `What is the grand total in the sales report?` | `1250` |
| `Which product sold the most in Q1?` | `Phones`, `200` |
| `What is the total in the broken budget?` | **refused**: harness found `ROW_TOTAL_MISMATCH` / `COLUMN_TOTAL_MISMATCH` |
| `What does the scanned report say?` (`doc_id=scanned_report`) | **refused**: 0 tables is a failure |

CLI without a server:

```bat
python -m qa.demo --root demo/docs --list
python -m qa.demo --root demo/docs --question "What were Laptops sales in Q1?"
```

To use real Docling output instead of the demo:

```bat
pip install -r requirements.txt
python -m engine.convert samples --out output
set DOCLING_OUTPUT_DIR=output
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Then `GET /health` reports `chunking_method` for each document. `"hybrid"` means
HybridChunker ran; `"markdown"` means the documented fallback ran because Docling was not
installed or the Docling JSON could not be reloaded. The Q&A policy is the same in both
cases: only `passed` tables can support an answer.

More detail: `qa/README.md`, `api/README.md`, and `docs/MEMBER3_SLIDES_GUIDE.md`.

---

## Quick start on Windows (everyone does this)

Requirements: **Python 3.12** (3.10 or newer works), internet for the first run, about 5 GB free disk.

**Option A: two double-clicks**

1. Unzip the project. Open the **inner** folder that contains `README.md` (you may see `docling_team_project\docling_team_project`).
2. Double-click `setup_windows.bat` (5-15 minutes). It must end green (no test failures).
3. Double-click `run_all.bat`. The first run downloads the AI models.

**Option B: manual commands (use this if a .bat fails)**

```
cd C:\path\to\docling-document-intelligence
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest -q
python -m engine.convert samples --out output
python compare_pdfplumber.py samples --out output_baseline
python compare_report.py
```

Replace `C:\path\to\docling-document-intelligence` with the real folder. You must see `(.venv)` at the start of the
line before `python` or `pip`. Open a new terminal later? Repeat the `cd` and the `activate.bat` lines.

### Which files does it accept, and what does it do when something goes wrong?

It does **not** accept "any" file. It accepts: PDF, Word `.docx`, PowerPoint `.pptx`, Excel `.xlsx`, HTML, and
images (`.png .jpg .tif`). Old `.doc`, `.ppt`, `.xls` files are ignored: save them as `.docx`, `.pptx`, `.xlsx` first.

| Situation | What the engine does |
|---|---|
| A file cannot be read (corrupt, password-protected, too big) | Marks it `failed` with the error, keeps going with the other files, exits with code 2 |
| A PDF gives 0 tables | Retries: fast, then accurate, then OCR + accurate (and the AI vision model if you pass `--vlm`). If still 0: status `no_tables` and a warning |
| Numbers like `1 234,56`, `1.234,56`, `(120)`, `$40` | Converted to numbers. `12%` and `5 TND` stay text. `1,500` is read as 1500 |
| Tables with merged cells | Flattened to rows and columns (multi-level headers are joined); the structure is not kept |

Options: `--accurate`, `--ocr`, `--vlm` (AI vision model: slow, large download, not tested), `--no-fallback`.
Everything is written to `output\run_report.json`: `ok`, `no_tables` or `failed` for every file.

**AI does not replace the checks.** Whatever Docling, OCR or the vision model extracts is only data. It must pass the
harness checksums (Member 2) before anyone answers from it. A table that is read wrongly but looks plausible is the
real danger, and only the checksums can catch it.

### Expected result of `python -m engine.convert samples --out output`

```
sample_simple_table.pdf: 1 table(s) [ok] -> output\sample_simple_table
sample_two_column_table.pdf: 1 table(s) [ok] -> output\sample_two_column_table
sample_wrong_total.pdf: 1 table(s) [ok] -> output\sample_wrong_total
sample_wrong_total_long_title.pdf: 0 table(s) [no_tables] -> output\sample_wrong_total_long_title  <- 0 tables
  WARNING: 0 tables found. ...
  attempts: fast=0, accurate=0, ocr+accurate=0
```

(each line also shows `[ok]` and the output folder; shortened here). The last PDF is expected to give 0 tables, and the retries take extra time. If your numbers differ, tell Member 1 and keep your output: it is a result.

### Docling command line (for the slides)

```
docling convert samples/sample_simple_table.pdf --to md --output cli_output
```

Options confirmed in `docling convert --help` for 2.151.1: `--to`, `--output`, `--table-mode fast|accurate`, `--ocr/--no-ocr`, `--device`.

---

## The team contract (JSON)

Member 1 produces tables in this format; everyone reads it:

```json
{
  "doc_id": "sample_simple_table",
  "table_id": "sample_simple_table_p1_t1",
  "page": 1,
  "columns": ["Item", "Q1", "Q2", "Q3", "Total"],
  "rows": [["Laptops", 120, 135, 150, 405], ["Total", 400, 410, 440, 1250]]
}
```

(abridged: real files contain every row). An empty cell is `null`. Member 2 returns one verdict per table:

```json
{ "table_id": "sample_simple_table_p1_t1", "passed": true, "reason": "" }
```

Member 3 answers only from tables with `passed: true`. A PDF with **0 tables** where one is expected counts as a failure.
Never rename a field without telling all four members the same day.

---

## Who does what

See `TEAM_PLAN.md`, and the README inside each folder (`harness/`, `api/`, `qa/`, `automation/`).

## Folder map

```
engine/               Member 1: PDF -> Docling -> contract JSON (contract.py needs no Docling)
fixtures/             5 hand-written tables (2 good, 3 broken) to build against
samples/              4 sample PDFs (made by make_samples.py)
harness/  tests/      Member 2: checksum validator and its pytest suite (tests/ already holds Member 1's tests)
api/  qa/             Member 3: FastAPI endpoints, chunking, grounded Q&A
demo/docs/            Member 3: hand-written output for API tests/demo (NOT Docling output)
automation/           Member 4: watch-folder / n8n, packaging, demo
docs/                 slide guide for Member 1
compare_pdfplumber.py baseline extractor (same output format)
compare_report.py     counts tables found per PDF for both tools
make_samples.py       regenerates samples/ (close the PDFs first)
setup_windows.bat, run_all.bat   Windows helpers
```

## Common problems

| Problem | Fix |
|---|---|
| `No module named engine` | You are not in the project folder: `cd` into the folder that contains `README.md` |
| `PermissionError` on a file | That file is open in Excel or a PDF viewer. Close it and run again |
| First run is very slow | Docling is downloading its models, once. Wait |
| `python` not found | Reinstall Python 3.12 with "Add python.exe to PATH" ticked, open a new terminal |
| `No module named 'encodings'` | Broken Python install: remove old Python versions and clean the PATH, then reinstall |
| `No module named 'fastapi'` (Member 3) | The light dependencies are not installed: `pip install -r requirements-api.txt` |
| `/convert` returns `503 Docling is not installed` | Expected on the light setup. Use `demo/docs`, or `pip install -r requirements.txt` and rerun the engine |
| `GET /health` shows `chunking_method: markdown` | Docling is not installed (or `.docling.json` cannot be reloaded), so the documented fallback ran. Install Docling and regenerate `output/` for HybridChunker |
| `0 tables for a PDF` | Expected for `sample_wrong_total_long_title.pdf`. The engine already retries; for others try `--vlm` and report it |
| `failed` for a file | Read the `ERROR:` line. Corrupt, password-protected or unsupported files cannot be read; the other files are still processed |

## Rules from the professor

Zero forcing, zero hallucinations, zero falsifications: every command in the slides must have been run by you,
and every claim needs a source link. Archive name: `Section_GroupNumber_20.zip`.
