"""
Drop a PDF, Word, Excel, HTML or image file in automation/inbox/ and the pipeline runs by itself:
  1. POST /convert/path  -> the API runs Docling (the engine) and the harness (harness)
  2. we print one verdict per table (PASS or FLAGGED, with the reason)
  3. optional: POST /ask -> a grounded answer, or a refusal if the table failed
  4. the full API response is saved in automation/results/<pdf name>.json

Run from the project root, with the virtual environment active.
Terminal 1:  python -m uvicorn api.main:app --port 8000
Terminal 2:  python automation/watch_folder.py
             python automation/watch_folder.py "What is the total?"   (with a question)
"""
import json
import os
import sys
import time
from pathlib import Path

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.convert import SUPPORTED_SUFFIXES  # noqa: E402

API = os.getenv("DOCLING_API_URL", "http://127.0.0.1:8000")
ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "automation" / "inbox"
RESULTS = ROOT / "automation" / "results"
QUESTION = None  # optional question, set from the command line in __main__


def wait_until_copied(path, timeout=120, pause=1.0):
    """A big file takes time to copy: wait until its size stops changing.

    Returns False if the file disappears or is still empty / growing after `timeout` seconds.
    """
    last = -1
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False  # deleted or renamed while being copied
        if size == last and size > 0:
            return True
        last = size
        time.sleep(pause)
    return False


def process(pdf, question=None):  # `pdf` is any supported file
    print(f"\n[1/3] Sending {pdf.name} to the API (Docling + harness) ...")
    try:
        r = requests.post(f"{API}/convert/path", json={"path": str(pdf)}, timeout=900)
        r.raise_for_status()
    except requests.RequestException as err:
        detail = ""
        if getattr(err, "response", None) is not None:  # the API answered with an error message
            detail = f": {err.response.text[:300]}"
        print(f"ERROR: the API call failed ({err}){detail}. Is uvicorn running?")
        return None
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

    if question and doc.get("doc_id"):
        print(f"[3/3] Question: {question}")
        try:
            r = requests.post(f"{API}/ask", json={"question": question, "doc_id": doc["doc_id"]},
                              timeout=120)
            r.raise_for_status()
            a = r.json()
            print(f"      {'REFUSED' if a['refused'] else 'ANSWER'}: {a['answer']}")
        except requests.RequestException as err:
            print(f"ERROR: the /ask call failed ({err})")
    print(f"Saved in {RESULTS / (pdf.stem + '.json')}")
    return data


class NewFile(FileSystemEventHandler):
    def handle(self, path):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return
        if not wait_until_copied(path):
            print(f"SKIPPED {path.name}: the file disappeared or is still being copied.")
            return
        process(path, QUESTION)

    def on_created(self, event):  # file copied into the inbox
        if not event.is_directory:
            self.handle(Path(event.src_path))

    def on_moved(self, event):  # file moved or renamed into the inbox
        if not event.is_directory and Path(event.dest_path).parent == INBOX:
            self.handle(Path(event.dest_path))


if __name__ == "__main__":
    QUESTION = sys.argv[1] if len(sys.argv) > 1 else None
    INBOX.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(NewFile(), str(INBOX), recursive=False)
    observer.start()
    print(f"Watching {INBOX}  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()