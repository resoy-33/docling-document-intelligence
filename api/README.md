# FastAPI service (`api/`)

Three required endpoints plus integration helpers:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/convert` | upload a PDF/DOCX/... and run the engine's Docling engine (multipart) |
| `POST` | `/convert/path` | same conversion for a file already on the server (JSON; for n8n/watch-folder) |
| `GET` | `/tables/{table_id}` | one table + the harness verdict + `usable` flag |
| `POST` | `/ask` | grounded answer, or a refusal with the reason |
| `GET` | `/tables` | list/filter tables (`?doc_id=...&passed=true`) |
| `GET` | `/documents` | document status, pass counts, chunking method |
| `GET` | `/documents/{doc_id}` | full document with tables and verdicts |
| `POST` | `/validate` | re-run the harness on the output folder |
| `POST` | `/reload` | re-scan the output folder after an external conversion |
| `GET` | `/health` | Docling availability, corpus counts, chunking methods |

Interactive OpenAPI page: **http://127.0.0.1:8000/docs**

## Run on the demo output (no Docling download)

```bat
setup.bat
run_api.bat demo
```

`run_api.bat demo` sets `DOCLING_OUTPUT_DIR=demo\docs` and starts uvicorn on port 8000.

Manual commands:

```bat
cd C:\path\to\repo
.venv\Scripts\activate.bat
set DOCLING_OUTPUT_DIR=demo\docs
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

## Run on real engine output

```bat
.venv\Scripts\activate.bat
pip install -r requirements.txt
python -m engine.convert samples --out output
set DOCLING_OUTPUT_DIR=output
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

If you convert while the API is running (from another shell), call `POST /reload` or use
`POST /convert`.

## Examples (PowerShell)

Health:

```powershell
curl.exe -s http://127.0.0.1:8000/health
```

Ask:

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/ask `
  -H "Content-Type: application/json" `
  -d "{\"question\":\"What were Laptops sales in Q1?\",\"doc_id\":\"sales_2026\"}"
```

One-line version:

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"What were Laptops sales in Q1?\"}"
```

Table + verdict:

```powershell
curl.exe -s http://127.0.0.1:8000/tables/broken_budget_p2_t1
```

Expected refusal (still HTTP 200):

```json
{
  "question": "What is the total in the broken budget?",
  "answer": "I cannot answer this question. the table that best matches this question failed deterministic verification; a failed table is never used to answer.",
  "grounded": false,
  "refused": true,
  "used_table_ids": ["broken_budget_p2_t1"],
  "warnings": ["Table broken_budget_p2_t1 (page 2) failed verification: ROW_TOTAL_MISMATCH: ..."]
}
```

Convert a file already on the server (best for the automation):

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/convert/path `
  -H "Content-Type: application/json" `
  -d "{\"path\":\"C:/path/to/report.pdf\",\"fallback\":true}"
```

Convert an uploaded file:

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/convert -F "file=@C:\path\to\report.pdf"
```

Re-run validation:

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/validate
```

## `POST /ask` request and response

Request:

```json
{ "question": "What were Laptops sales in Q1?", "doc_id": "sales_2026", "top_k": 5 }
```

Response fields:

| Field | Meaning |
|---|---|
| `answer` | answer text with `Source: doc, page, table` |
| `grounded` | `true` only if the number check passed |
| `refused` | `true` when the system refuses (failed table, 0 tables, no evidence) |
| `reason` | why it refused |
| `citations` | doc, page, table, row (0-based), column, row label, quote |
| `used_table_ids` | table(s) that supported the answer |
| `warnings` | failed competing tables, non-verifiable table, LLM rejection |
| `retrieved_chunk_ids` | evidence trail for the slides/demo |
| `method` | `extractive` or `llm+grounding-check` |

`refused: true` is a **successful** refusal, not an HTTP error. The automation should display
the answer and the warning.

## Error codes

| Code | When |
|---|---|
| `400` | no file/path, unsupported extension, missing output folder for `/validate` |
| `404` | unknown table id / document id / server-side file |
| `422` | invalid request body (empty question, `top_k` out of range) |
| `503` | `/convert` called while Docling is not installed |
| `500` | unexpected conversion crash (the engine's per-file failures are returned as `status: "failed"` with HTTP 200) |

## Integration notes for the automation

* **Watch-folder:** when a new PDF appears, call `POST /convert/path` with
  `{"path": "C:/.../file.pdf"}`. The response contains `summary.status`
  (`ok`, `no_tables`, `failed`), the document's tables/verdicts, and `stats`.
* **n8n:** use an HTTP Request node, method `POST`, URL
  `http://127.0.0.1:8000/convert/path`, JSON body with the file path. Then call `POST /ask`.
* **After external conversion:** if the engine runs outside the API, call `POST /reload`.
* **Demo answers:** use `doc_id` to avoid ambiguity between documents. The response always
  includes a page and table citation.

## Tests

```bat
python -m pytest -q tests\test_api.py
```

Covers health, documents, table filters, table verdict/usability, grounded ask, refusal,
request validation, `/validate`, `/reload`, 503 without Docling, `/convert` with a fake
engine, `/convert/path`, unsupported extensions, and missing input.

Whole project suite: `127 passed, 2 skipped` (the 2 skips are Docling-only
tests from the engine). A real uvicorn server was also started on `127.0.0.1:8010` and
checked with HTTP requests for `/health`, `/ask`, `/tables/{id}`, `/validate` and
`/openapi.json`.

## Security / scope

This is a local academic demo. There is no authentication, authorization, rate limiting or
sandboxing. `/convert/path` reads a server-side path, so do not expose the API to an
untrusted network. Uploaded files are stored under `uploads/` (git-ignored).
