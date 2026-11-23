# Automation (Member 4): watch-folder

A PDF dropped in `automation/inbox/` goes through the whole pipeline by itself:
Docling (Member 1) -> checksum harness (Member 2) -> API and grounded answers (Member 3).
Each table gets a verdict: PASS (can be used to answer) or FLAGGED (never used to answer).

`<PROJECT_ROOT>` below means the folder that contains `README.md`, `engine/`, `api/` and `automation/`.
Use PowerShell on Windows. Keep the quotes if the path contains spaces.

## 1. One-time setup (about 10 to 15 minutes, Docling is large)

```powershell
cd "<PROJECT_ROOT>"
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install watchdog requests
```

If PowerShell blocks the activation script, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

You should see `(.venv)` at the start of the prompt.

## 2. Terminal 1: start the API

```powershell
cd "<PROJECT_ROOT>"
.venv\Scripts\Activate.ps1
python -m uvicorn api.main:app --port 8000
```

Expected: `Uvicorn running on http://127.0.0.1:8000`. API docs: http://127.0.0.1:8000/docs

## 3. Terminal 2: start the watch-folder

```powershell
cd "<PROJECT_ROOT>"
.venv\Scripts\Activate.ps1
python automation/watch_folder.py "What is the total?"
```

The question is optional. Without it, the script only converts and prints verdicts.

## 4. Terminal 3: drop a PDF

```powershell
cd "<PROJECT_ROOT>"
Copy-Item samples\sample_simple_table.pdf automation\inbox\
Copy-Item samples\sample_wrong_total.pdf automation\inbox\
```

The first conversion is slow because Docling downloads its models. Wait for the first result before dropping the second PDF.

## Expected output

| PDF | Result | Answer |
|---|---|---|
| `sample_simple_table.pdf` | `PASS` | `Total: 1250`, with source page 1 and the table id |
| `sample_wrong_total.pdf` | `FLAGGED` (`ROW_TOTAL_MISMATCH`, cells add up to 1250, Total says 1300) | `REFUSED` |

The full API response for each PDF is saved in `automation/results/<pdf name>.json`.

## Troubleshooting

- `ERROR: the API call failed`: the API in Terminal 1 is not running. Start it (step 2).
- 503 error from the API: Docling is not installed in this environment. Redo step 1.
- Nothing happens after dropping a PDF: check that the file is in `automation/inbox/` and ends in `.pdf`.
- Stop any terminal with `Ctrl+C`.

## Security note

Local academic demo: the API has no authentication and `/convert/path` reads a path on the server. Do not expose it to an untrusted network.
