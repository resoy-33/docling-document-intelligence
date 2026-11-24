"""Watch-folder automation: file in inbox -> POST /convert/path -> harness verdicts -> POST /ask.

The HTTP calls of automation/watch_folder.py are routed to the real FastAPI app in memory
(TestClient), with a fake Docling engine, so no server and no models are needed.
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import requests
from fastapi.testclient import TestClient

from api.main import create_app

ROOT = Path(__file__).resolve().parent.parent


def load_watch_folder():
    spec = importlib.util.spec_from_file_location("watch_folder", ROOT / "automation" / "watch_folder.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_engine(total_row):
    """A fake converter that writes one table, with a correct or a wrong Total row."""
    def convert(source, out_root, accurate=False, ocr=False, fallback=True):
        doc_id = Path(source).stem
        folder = Path(out_root) / doc_id
        (folder / "tables").mkdir(parents=True, exist_ok=True)
        table = {"doc_id": doc_id, "table_id": f"{doc_id}_p1_t1", "page": 1,
                 "columns": ["Item", "Q1", "Q2", "Total"],
                 "rows": [["A", 10, 20, 30], ["B", 5, 5, 10], total_row]}
        (folder / "tables" / f"{doc_id}_p1_t1.json").write_text(json.dumps(table), encoding="utf-8")
        summary = {"doc_id": doc_id, "source": str(source), "status": "ok", "n_tables": 1,
                   "table_ids": [table["table_id"]]}
        (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary
    return convert


def wire(monkeypatch, tmp_path, total_row):
    module = load_watch_folder()
    app = create_app(tmp_path / "output", docling_check=lambda: True,
                     convert_file_func=fake_engine(total_row), prefer_hybrid=False)
    client = TestClient(app)

    def post(url, json=None, timeout=None):  # requests.post -> in-memory API
        response = client.post(url.replace(module.API, ""), json=json)
        return SimpleNamespace(json=response.json, raise_for_status=lambda: None)

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module, "RESULTS", tmp_path / "results")
    inbox_file = tmp_path / "invoice.pdf"
    inbox_file.write_bytes(b"%PDF-1.4 fake")
    return module, inbox_file


def test_correct_table_passes_and_question_is_answered(monkeypatch, tmp_path, capsys):
    module, path = wire(monkeypatch, tmp_path, ["Total", 15, 25, 40])
    data = module.process(path, question="What is the total for A?")
    out = capsys.readouterr().out
    assert data["document"]["verdicts"][0]["passed"]
    assert "PASS  invoice_p1_t1" in out and "ANSWER:" in out and "30" in out
    assert (tmp_path / "results" / "invoice.json").exists()


def test_wrong_total_is_flagged_and_question_is_refused(monkeypatch, tmp_path, capsys):
    module, path = wire(monkeypatch, tmp_path, ["Total", 15, 25, 99])
    module.process(path, question="What is the total for A?")
    out = capsys.readouterr().out
    assert "FLAGGED  invoice_p1_t1" in out and "ROW_TOTAL_MISMATCH" in out
    assert "REFUSED:" in out


def test_api_down_is_reported_not_raised(monkeypatch, tmp_path, capsys):
    module = load_watch_folder()

    def down(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(module.requests, "post", down)
    path = tmp_path / "a.pdf"
    path.write_bytes(b"x")
    assert module.process(path) is None
    assert "Is uvicorn running?" in capsys.readouterr().out


def test_wait_until_copied(tmp_path):
    module = load_watch_folder()
    done = tmp_path / "done.pdf"
    done.write_bytes(b"content")
    assert module.wait_until_copied(done, timeout=5, pause=0.05) is True
    assert module.wait_until_copied(tmp_path / "gone.pdf", timeout=1, pause=0.05) is False
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert module.wait_until_copied(empty, timeout=0.3, pause=0.05) is False  # no endless loop
