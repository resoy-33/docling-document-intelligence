# Layout-Aware Document Intelligence & Table Structure Reconstruction Harness with IBM Docling

Subject #20 (DS1 SOA): a pipeline that turns complex PDFs into verified tables,
and only answers questions from tables that passed deterministic checks.

```
PDF dropped in a watch-folder 
  -> Docling (layout analysis + TableFormer)        
  -> tables as JSON in the team contract            
  -> checksum validation (Pydantic v2 + pytest)     
  -> chunking, FastAPI, grounded Q&A               
  -> automation, packaging, demo                   
```

Official reference: https://github.com/docling-project/docling

## Run the full demo (start here)

This is the end-to-end demo: a PDF dropped in a folder becomes a verified answer, or a refusal.
Everything is explained step by step in [`automation/README.md`](automation/README.md). In short, with
**three PowerShell windows**, each starting with `cd` into the project folder and activating the environment:

```powershell
cd "C:\path\to\docling-document-intelligence"
.venv\Scripts\Activate.ps1
```

| Window | Command | Role |
|---|---|---|
| 1 | `python -m uvicorn api.main:app --port 8000` 
| 2 | `python automation/watch_folder.py "What is the total?"` 
| 3 | `Copy-Item samples\sample_simple_table.pdf automation\inbox\` then `Copy-Item samples\sample_wrong_total.pdf automation\inbox\` | drop the PDFs |

Expected: `sample_simple_table.pdf` gives `PASS` and the answer `Total: 1250` with page and table cited;
`sample_wrong_total.pdf` gives `FLAGGED` (`ROW_TOTAL_MISMATCH`: cells add up to 1250, the Total row says 1300)
and the answer is `REFUSED`. The first conversion is slow (Docling downloads its models once).

---

## Quick start on Windows 

Requirements: **Python 3.12** (3.10 or newer works), internet for the first run, about 5 GB free disk.

In **PowerShell** (the default Windows terminal):

```powershell
cd "C:\path\to\docling-document-intelligence"
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest -q
python -m engine.convert samples --out output
python compare_pdfplumber.py samples --out output_baseline
python compare_report.py
```

In **cmd.exe**, replace the activation line with `.venv\Scripts\activate.bat`.
Do **not** use `activate.bat` in PowerShell: it runs without error but does not activate anything, and the packages
then go into your global Python. If PowerShell refuses `Activate.ps1`, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Replace `C:\path\to\docling-document-intelligence` with the real folder, and keep the quotes if the path contains
spaces. You must see `(.venv)` at the start of the line before `python` or `pip`. Open a new terminal later?
Repeat the `cd` and the activation lines.


| Situation | What the engine does |
|---|---|
| A file cannot be read (corrupt, password-protected, too big) | Marks it `failed` with the error, keeps going with the other files, exits with code 2 |
| A PDF gives 0 tables | Retries: fast, then accurate, then OCR + accurate (and the AI vision model if you pass `--vlm`). If still 0: status `no_tables` and a warning |
| Numbers like `1 234,56`, `1.234,56`, `(120)`, `$40` | Converted to numbers. `12%` and `5 TND` stay text. `1,500` is read as 1500 |
| Tables with merged cells | Flattened to rows and columns (multi-level headers are joined); the structure is not kept |

Options: `--accurate`, `--ocr`, `--vlm` (AI vision model: slow, large download, not tested), `--no-fallback`.
Everything is written to `output\run_report.json`: `ok`, `no_tables` or `failed` for every file.

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

---

## API + grounded Q&A, no Docling download 

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

Manual commands (PowerShell):

```powershell
cd "C:\path\to\docling-document-intelligence"
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-api.txt
python demo\make_demo.py
python -m pytest -q
$env:DOCLING_OUTPUT_DIR = "demo\docs"
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

(cmd.exe: `.venv\Scripts\activate.bat` and `set DOCLING_OUTPUT_DIR=demo\docs`.)

CLI without a server:

```powershell
python -m qa.demo --root demo/docs --list
python -m qa.demo --root demo/docs --question "What were Laptops sales in Q1?"
```

To use real Docling output instead of the demo:

```powershell
pip install -r requirements.txt
python -m engine.convert samples --out output
$env:DOCLING_OUTPUT_DIR = "output"
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Then `GET /health` reports `chunking_method` for each document. `"hybrid"` means
HybridChunker ran; `"markdown"` means the documented fallback ran because Docling was not
installed or the Docling JSON could not be reloaded. The Q&A policy is the same in both
cases: only `passed` tables can support an answer.

More detail: `qa/README.md`, `api/README.md`, and `docs/MEMBER3_SLIDES_GUIDE.md`.

### API endpoints (for the slides and the sequence diagram)

| Endpoint | Purpose |
|---|---|
| `POST /convert` | Convert an uploaded `file`, or a server-side `path` sent as a form field |
| `POST /convert/path` | JSON `{"path": "<absolute path>"}`: used by the watch-folder (no multipart) |
| `GET /tables/{id}` | One table with its verdict: `{table, verdict, usable}` |
| `POST /ask` | `{"question": ..., "doc_id": ...}` returns a grounded answer with citations, or a refusal (`refused: true`) |
| `GET /health`, `/documents`, `/tables`, `POST /validate`, `POST /reload` | Status and maintenance |
---

## Folder map
```
engine/               PDF -> Docling -> contract JSON (contract.py needs no Docling)
fixtures/             5 hand-written tables (2 good, 3 broken) to build against
samples/              4 sample PDFs (made by make_samples.py)
harness/  tests/      checksum validator and its pytest suite 
api/  qa/             FastAPI endpoints, chunking, grounded Q&A
demo/docs/            hand-written output for API tests/demo (NOT Docling output)
automation/           watch_folder.py, README.md, inbox/ (PDFs in), results/ (API responses out)
screenshots/          high-resolution screenshots of the install, API, watch-folder and tests
compare_pdfplumber.py baseline extractor (same output format)
compare_report.py     counts tables found per PDF for both tools
make_samples.py       regenerates samples
setup_windows.bat, run_all.bat   Windows helpers
```
