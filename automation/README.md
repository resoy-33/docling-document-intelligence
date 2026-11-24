# Automation: watch-folder

A file dropped in `automation/inbox/` goes through the whole pipeline by itself:
Docling → checksum harness → API → grounded answer or refusal.
Supported: PDF, DOCX, PPTX, XLSX, HTML, PNG, JPG, TIFF.
Each table gets a verdict: PASS (can be used to answer) or FLAGGED (never used to answer).

## Setup (once)

`setup.bat full` from the project folder (about 10–15 minutes, Docling is large).
Manual alternative in PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks the activation script, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Run (three windows, from the project folder)

```powershell
# window 1: the API  (normal mode: `run_api.bat demo` would write the conversions into demo\docs)
run_api.bat                     # or: python -m uvicorn api.main:app --port 8000
# window 2: the watch-folder (the question is optional)
run_watch.bat "What is the total?"   # or: python automation/watch_folder.py "What is the total?"
# window 3: drop the files, one at a time
Copy-Item samples\sample_simple_table.pdf automation\inbox\
Copy-Item samples\sample_wrong_total.pdf  automation\inbox\
```

The first conversion is slow (Docling loads or downloads its models). Wait for the first result
before dropping the second file. API docs: http://127.0.0.1:8000/docs

## Expected output

| File | Result | Answer |
|---|---|---|
| `sample_simple_table.pdf` | `PASS` | `Total: 1250`, with source page 1 and the table id |
| `sample_wrong_total.pdf` | `FLAGGED` (`ROW_TOTAL_MISMATCH`: cells add up to 1250, the Total row says 1300) | `REFUSED` |

Each full API response is saved in `automation/results/<file name>.json`.
Files copied **or moved** into the inbox are processed. A file that is deleted or stays empty while
being copied is skipped with a message (no endless wait).

## Troubleshooting

- `ERROR: the API call failed`: the API in window 1 is not running. Start it.
- 503 error from the API: Docling is not installed in this environment. Run `setup.bat full`.
- Nothing happens after dropping a file: check that it is in `automation/inbox/` and is a supported type.
- API on another port: `set DOCLING_API_URL=http://127.0.0.1:8765` before starting the watch-folder.
- Stop any window with `Ctrl+C`.

Webhook/n8n alternative: an HTTP Request node doing `POST http://127.0.0.1:8000/convert/path`
with `{"path": "<file>"}`, then `POST /ask`.

**Security note:** local academic demo. The API has no authentication and `/convert/path` reads a
path on the server. Do not expose it to an untrusted network.
