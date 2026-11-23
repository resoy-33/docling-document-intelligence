# Layout-Aware Document Intelligence & Table Structure Reconstruction Harness with IBM Docling

Subject #20 (DS1). Team project: a pipeline that turns complex PDFs into verified tables,
and only answers questions from tables that passed deterministic checks.

```
PDF dropped in a watch-folder (n8n webhook = possible extension, not built)
  -> Docling (layout analysis + TableFormer)        [Member 1: engine/]
  -> tables as JSON in the team contract            [Member 1: engine/]
  -> checksum validation (Pydantic v2 + pytest)     [Member 2: harness/, tests/]
  -> chunking, FastAPI, grounded Q&A                [Member 3: api/, qa/]
  -> automation, packaging, demo                    [Member 4: automation/]
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
| 1 | `python -m uvicorn api.main:app --port 8000` | API (Member 3) |
| 2 | `python automation/watch_folder.py "What is the total?"` | watch-folder (Member 4) |
| 3 | `Copy-Item samples\sample_simple_table.pdf automation\inbox\` then `Copy-Item samples\sample_wrong_total.pdf automation\inbox\` | drop the PDFs |

Expected: `sample_simple_table.pdf` gives `PASS` and the answer `Total: 1250` with page and table cited;
`sample_wrong_total.pdf` gives `FLAGGED` (`ROW_TOTAL_MISMATCH`: cells add up to 1250, the Total row says 1300)
and the answer is `REFUSED`. The first conversion is slow (Docling downloads its models once).

---

## What is verified and what is not

| Item | Status |
|---|---|
| `engine/convert.py` on 3 sample PDFs with Docling 2.151.1 on Windows | Run by Yosr: 1 table each for `sample_simple_table`, `sample_two_column_table` and `sample_wrong_total` |
| `sample_wrong_total_long_title.pdf` | Docling found **0 tables** (normal, OCR, accurate, OCR+accurate), and the CLI labelled the table as an image. Cause not established. Kept as a real failure case |
| `pytest` suite (121 collected) | **121 passed, 0 skipped** on Windows/Python 3.12 with Docling 2.151.1 installed, run by Member 4 on 2026-11-22 (about 17 s). Member 3 reported 119 passed and 2 skipped on a machine without Docling: the 2 skips are Member 1's Docling-only tests, which run once Docling is installed |
| Word, Excel and HTML input (real Docling run, 3 files) | Worked in the author's test environment: 1 table each; number formats parsed. Not tested on your PCs |
| PDF retry cascade (fast, accurate, OCR + accurate) and the AI vision option `--vlm` | Logic tested with fake converters only. The real PDF cascade and `--vlm` have **not** been run |
| Scanned PDFs, borderless tables, merged cells, images, PowerPoint | **Not tested** |
| `setup_windows.bat`, `run_all.bat` | Written but **not tested on Windows**. If one fails, use the manual commands below |
| Table content correctness across tools | **Not measured yet**: needs Member 2's validator and harder PDFs |
| **Member 3: chunking, API, grounded Q&A** | Implemented and tested: `119 passed, 2 skipped` for the whole suite; real uvicorn server checked on `/health`, `/ask`, `/tables/{id}`, `/validate`, `/openapi.json` |
| **Member 3: HybridChunker** | Code path implemented; **not executed** on the test machine because Docling was not installed there. The labelled Markdown fallback ran instead (`chunking_method` is exposed by the API) |
| **Member 3: demo corpus** | Hand-written for API/Q&A tests, **not** Docling output; stated in `demo/docs/README.md` |
| **Member 4: watch-folder end to end** (2026-11-22, Windows, Python 3.12, Docling 2.151.1, real API) | Run by Member 4: `sample_simple_table.pdf` -> `PASS`, answer `Total: 1250` with page 1 and table id; `sample_wrong_total.pdf` -> `FLAGGED` (`ROW_TOTAL_MISMATCH` and `COLUMN_TOTAL_MISMATCH`), answer `REFUSED`. Full responses are saved in `automation/results/` |
| **Member 4: not done or not tested** | n8n webhook (not built), Celery (not used), Docker (not built), the other two sample PDFs through the watch-folder, scanned PDFs, running the watch-folder on a different machine |

---

## Quick start on Windows (everyone does this)

Requirements: **Python 3.12** (3.10 or newer works), internet for the first run, about 5 GB free disk.

**Option A: two double-clicks**

1. Unzip the project. Open the **inner** folder that contains `README.md` (you may see `docling_team_project\docling_team_project`).
2. Double-click `setup_windows.bat` (5-15 minutes). It must end green (no test failures).
3. Double-click `run_all.bat`. The first run downloads the AI models.

**Option B: manual commands (use this if a .bat fails)**

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

Tip: avoid unzipping into a OneDrive folder. Docling and its models are several GB and OneDrive tries to sync them.
A short path such as `C:\ds1` is safer.

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

Demo questions (the API returns a citation or a refusal with a reason):

| Question | Expected |
|---|---|
| `What were Laptops sales in Q1?` (`doc_id=sales_2026`) | `120`, page 1, table `sales_2026_p1_t1` |
| `What is the grand total in the sales report?` | `1250` |
| `Which product sold the most in Q1?` | `Phones`, `200` |
| `What is the total in the broken budget?` | **refused**: harness found `ROW_TOTAL_MISMATCH` / `COLUMN_TOTAL_MISMATCH` |
| `What does the scanned report say?` (`doc_id=scanned_report`) | **refused**: 0 tables is a failure |

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

## Member 4: automation (watch-folder)

`automation/watch_folder.py` watches `automation/inbox/` with the `watchdog` library. For each new PDF it:

1. waits until the file is fully copied,
2. calls `POST /convert/path` on the API (Docling extraction and checksum verdicts),
3. prints one verdict per table: `PASS`, or `FLAGGED` with the reason,
4. optionally asks a question through `POST /ask` and prints the answer or the refusal,
5. saves the full API response in `automation/results/<pdf name>.json`.

Install the two extra packages once: `pip install watchdog requests` (they are also listed in `requirements.txt`).
Run steps, expected output and troubleshooting: [`automation/README.md`](automation/README.md).

Why a watch-folder and not n8n or Celery: it needs no extra service (watchdog is a pip package), n8n needs an
n8n instance and Celery needs a message broker (RabbitMQ or Redis). Sources are listed in the slides. n8n is a
possible next step: `POST /convert/path` was designed so a webhook workflow can call it.

Security note: local academic demo only. The API has no authentication and `/convert/path` reads a path on the
server machine. Do not expose it to an untrusted network.

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

The API also adds `doc_id`, `page`, `verifiable` and `codes` to each verdict; the three fields above are unchanged.
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
automation/           Member 4: watch_folder.py, README.md, inbox/ (PDFs in), results/ (API responses out)
screenshots/          Member 4: high-resolution screenshots of the install, API, watch-folder and tests
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
| No `(.venv)` in the prompt in PowerShell | You used `activate.bat`. In PowerShell use `.venv\Scripts\Activate.ps1` |
| `PermissionError` on a file | That file is open in Excel or a PDF viewer. Close it and run again |
| First run is very slow | Docling is downloading its models, once. Wait |
| `python` not found | Reinstall Python 3.12 with "Add python.exe to PATH" ticked, open a new terminal |
| `No module named 'encodings'` | Broken Python install: remove old Python versions and clean the PATH, then reinstall |
| `No module named 'fastapi'` (Member 3) | The light dependencies are not installed: `pip install -r requirements-api.txt` |
| `No module named 'watchdog'` or `'requests'` (Member 4) | `pip install watchdog requests` |
| `/convert` returns `503 Docling is not installed` | Expected on the light setup. Use `demo/docs`, or `pip install -r requirements.txt` and rerun the engine |
| `ERROR: the API call failed` in the watch-folder | The API is not running. Start it in another window (`python -m uvicorn api.main:app --port 8000`) |
| `file not found` (404) from `/convert/path` | The path must be a full path to a file on the same machine as the API |
| `GET /health` shows `chunking_method: markdown` | Docling is not installed (or `.docling.json` cannot be reloaded), so the documented fallback ran. Install Docling and regenerate `output/` for HybridChunker |
| `0 tables for a PDF` | Expected for `sample_wrong_total_long_title.pdf`. The engine already retries; for others try `--vlm` and report it |
| `failed` for a file | Read the `ERROR:` line. Corrupt, password-protected or unsupported files cannot be read; the other files are still processed |

