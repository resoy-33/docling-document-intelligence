# Automation: watch-folder

A file dropped in `automation/inbox/` goes through the whole pipeline by itself:
Docling → checksum harness → API → grounded answer or refusal. Supported: PDF, DOCX, PPTX, XLSX, HTML, images.

```powershell
# window 1  (normal mode: `run_api.bat demo` would write the conversions into demo\docs)
run_api.bat
# window 2
run_watch.bat "What is the total?"
# window 3
Copy-Item samples\sample_simple_table.pdf automation\inbox\
Copy-Item samples\sample_wrong_total.pdf  automation\inbox\
```

Expected: `sample_simple_table.pdf` → `PASS`, answer `Total: 1250` with page and table cited;
`sample_wrong_total.pdf` → `FLAGGED` (`ROW_TOTAL_MISMATCH`: cells add up to 1250, the Total row says 1300)
and the answer is `REFUSED`. The first conversion is slow (Docling downloads its models once).

Each full API response is saved in `automation/results/<file name>.json`.
Files copied **or moved** into the inbox are processed. A file that is deleted or stays empty while
being copied is skipped with a message (no endless wait). If the API is not on port 8000, set
`DOCLING_API_URL` (for example `set DOCLING_API_URL=http://127.0.0.1:8765`).
Webhook/n8n alternative: an HTTP Request node doing `POST http://127.0.0.1:8000/convert/path`
with `{"path": "<file>"}`, then `POST /ask`.
