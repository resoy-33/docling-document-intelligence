"""
Drop a PDF in automation/inbox/ and the pipeline runs by itself:
  1. POST /convert/path  -> the API runs Docling (Member 1) and the harness (Member 2)
  2. we print one verdict per table (PASS or FLAGGED, with the reason)
  3. optional: POST /ask -> a grounded answer, or a refusal if the table failed
  4. the full API response is saved in automation/results/<pdf name>.json

Run from the project root, with the virtual environment active.
Terminal 1:  python -m uvicorn api.main:app --port 8000
Terminal 2:  python automation/watch_folder.py
             python automation/watch_folder.py "What is the total?"   (with a question)
"""
import json
import sys
import time
from pathlib import Path

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

API = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "automation" / "inbox"
RESULTS = ROOT / "automation" / "results"
QUESTION = sys.argv[1] if len(sys.argv) > 1 else None


def wait_until_copied(path):
    """A big file takes time to copy: wait until its size stops changing."""
    last = -1
    while True:
        size = path.stat().st_size
        if size == last and size > 0:
            return
        last = size
        time.sleep(1)


def process(pdf):
    print(f"\n[1/3] Sending {pdf.name} to the API (Docling + harness) ...")
    try:
        r = requests.post(f"{API}/convert/path", json={"path": str(pdf)}, timeout=900)
        r.raise_for_status()
    except requests.RequestException as err:
        print(f"ERROR: the API call failed ({err}). Is uvicorn running?")
        return
    data = r.json()

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{pdf.stem}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    print(f"[2/3] Extraction status: {data['summary'].get('status')}")
    doc = data.get("document") or {}
    for v in doc.get("verdicts", []):
        label = "PASS" if v["passed"] else "FLAGGED"
        print(f"      {label}  {v['table_id']}  {v.get('reason', '')}")
    if not doc.get("verdicts"):
        print("      no table found: nothing can be used to answer")

    if QUESTION and doc.get("doc_id"):
        print(f"[3/3] Question: {QUESTION}")
        a = requests.post(f"{API}/ask",
                          json={"question": QUESTION, "doc_id": doc["doc_id"]}).json()
        print(f"      {'REFUSED' if a['refused'] else 'ANSWER'}: {a['answer']}")
    print(f"Saved in {RESULTS / (pdf.stem + '.json')}")


class NewPdf(FileSystemEventHandler):
    def on_created(self, event):
        path = Path(event.src_path)
        if event.is_directory or path.suffix.lower() != ".pdf":
            return
        wait_until_copied(path)
        process(path)


if __name__ == "__main__":
    INBOX.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(NewPdf(), str(INBOX), recursive=False)
    observer.start()
    print(f"Watching {INBOX}  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()