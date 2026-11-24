"""API tests: endpoints, refusal policy, conversion adapter with a fake engine."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

DEMO = Path(__file__).parent.parent / "demo" / "docs"


def write_fake_conversion(out_root: Path, doc_id: str = "uploaded_doc") -> dict:
    folder = out_root / doc_id
    (folder / "tables").mkdir(parents=True, exist_ok=True)
    table = {
        "doc_id": doc_id,
        "table_id": f"{doc_id}_p1_t1",
        "page": 1,
        "columns": ["Item", "Q1", "Total"],
        "rows": [["A", 10, 10], ["B", 5, 5], ["Total", 15, 15]],
    }
    (folder / "tables" / f"{doc_id}_p1_t1.json").write_text(
        json.dumps(table), encoding="utf-8"
    )
    summary = {
        "doc_id": doc_id,
        "source": str(folder / "uploaded.pdf"),
        "status": "ok",
        "n_tables": 1,
        "table_ids": [table["table_id"]],
    }
    (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (folder / f"{doc_id}.md").write_text(
        "<!-- page: 1 -->\n# Uploaded document\nA fake conversion for tests.\n",
        encoding="utf-8",
    )
    return summary


@pytest.fixture()
def demo_root(tmp_path):
    root = tmp_path / "docs"
    shutil.copytree(DEMO, root)
    return root


@pytest.fixture()
def client(demo_root):
    app = create_app(
        demo_root,
        docling_check=lambda: False,
        upload_dir=demo_root.parent / "uploads",
    )
    return TestClient(app)


def test_root_and_health(client):
    assert client.get("/").status_code == 200
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["documents"] == 5
    assert data["tables"] == 4
    assert data["tables_passed"] == 3
    assert data["docling_available"] is False
    assert "passed" in data["qa_policy"]


def test_documents_and_document_detail(client):
    response = client.get("/documents")
    assert response.status_code == 200
    by_id = {item["doc_id"]: item for item in response.json()}
    assert by_id["broken_budget"]["n_passed"] == 0
    assert by_id["broken_budget"]["pass_rate_tables"] == 0.0
    assert by_id["scanned_report"]["n_tables"] == 0
    assert by_id["scanned_report"]["issue"].startswith("0 tables found")

    detail = client.get("/documents/sales_2026")
    assert detail.status_code == 200
    assert detail.json()["tables"][0]["table_id"] == "sales_2026_p1_t1"

    assert client.get("/documents/nope").status_code == 404


def test_tables_list_and_filters(client):
    response = client.get("/tables")
    assert response.status_code == 200
    assert len(response.json()) == 4

    passed = client.get("/tables", params={"passed": "true"}).json()
    assert {item["table"]["table_id"] for item in passed} == {
        "sales_2026_p1_t1", "regions_2026_p1_t1", "team_roster_p1_t1"
    }

    failed = client.get("/tables", params={"passed": "false"}).json()
    assert [item["table"]["table_id"] for item in failed] == ["broken_budget_p2_t1"]
    assert failed[0]["usable"] is False


def test_get_table_returns_verdict_and_usability(client):
    good = client.get("/tables/sales_2026_p1_t1")
    assert good.status_code == 200
    body = good.json()
    assert body["usable"] is True
    assert body["verdict"]["passed"] is True
    assert body["table"]["rows"][-1] == ["Total", 400, 410, 440, 1250]

    bad = client.get("/tables/broken_budget_p2_t1")
    assert bad.status_code == 200
    assert bad.json()["usable"] is False
    assert "ROW_TOTAL_MISMATCH" in bad.json()["verdict"]["codes"]

    assert client.get("/tables/does_not_exist").status_code == 404


def test_ask_grounded(client):
    response = client.post(
        "/ask",
        json={"question": "What were Laptops sales in Q1?", "doc_id": "sales_2026"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert "120" in body["answer"]
    assert body["citations"][0]["page"] == 1


def test_ask_refuses_failed_table(client):
    response = client.post(
        "/ask",
        json={"question": "What is the total in the broken budget?", "doc_id": "broken_budget"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["grounded"] is False
    assert any("ROW_TOTAL_MISMATCH" in warning for warning in body["warnings"])


def test_ask_validates_request(client):
    assert client.post("/ask", json={"question": ""}).status_code == 422
    assert client.post("/ask", json={"question": "x", "top_k": 0}).status_code == 422


def test_validate_uses_member2_harness(client):
    response = client.post("/validate")
    assert response.status_code == 200
    data = response.json()
    assert data["n_tables"] == 4
    assert data["n_tables_passed"] == 3
    assert data["pass_rate_tables"] == 0.75
    assert data["n_docs"] == 5
    assert data["n_docs_passed"] == 3
    assert {issue["code"] for issue in data["doc_issues"]} == {"NO_TABLES"}


def test_reload(client):
    response = client.post("/reload")
    assert response.status_code == 200
    assert response.json()["reloaded"] is True
    assert response.json()["tables"] == 4


def test_convert_returns_503_without_docling(demo_root):
    app = create_app(
        demo_root,
        docling_check=lambda: False,
        upload_dir=demo_root.parent / "uploads",
    )
    client = TestClient(app)
    response = client.post(
        "/convert",
        files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 503
    assert "Docling is not installed" in response.json()["detail"]


def test_convert_with_fake_engine_and_then_ask(tmp_path):
    root = tmp_path / "docs"
    shutil.copytree(DEMO, root)
    calls = {}

    def fake_convert(source, out_root, accurate=False, ocr=False, fallback=True):
        calls["source"] = Path(source)
        calls["fallback"] = fallback
        return write_fake_conversion(Path(out_root))

    app = create_app(
        root,
        docling_check=lambda: True,
        convert_file_func=fake_convert,
        upload_dir=tmp_path / "uploads",
    )
    client = TestClient(app)
    response = client.post(
        "/convert",
        files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"fallback": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["doc_id"] == "uploaded_doc"
    assert body["document"]["n_passed"] == 1
    assert body["stats"]["documents"] == 6
    assert calls["source"].suffix == ".pdf"
    assert calls["fallback"] is True

    answer = client.post(
        "/ask",
        json={"question": "What is the total for A?", "doc_id": "uploaded_doc"},
    )
    assert answer.status_code == 200
    assert "10" in answer.json()["answer"]


def test_convert_path_json_endpoint(tmp_path):
    root = tmp_path / "docs"
    shutil.copytree(DEMO, root)
    source = tmp_path / "server_side.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    def fake_convert(source, out_root, accurate=False, ocr=False, fallback=True):
        return write_fake_conversion(Path(out_root), doc_id="path_doc")

    app = create_app(
        root,
        docling_check=lambda: True,
        convert_file_func=fake_convert,
        upload_dir=tmp_path / "uploads",
    )
    client = TestClient(app)
    response = client.post("/convert/path", json={"path": str(source)})
    assert response.status_code == 200
    assert response.json()["summary"]["doc_id"] == "path_doc"

    assert client.post(
        "/convert/path", json={"path": str(tmp_path / "missing.pdf")}
    ).status_code == 404


def test_convert_rejects_unsupported_extension(tmp_path):
    root = tmp_path / "docs"
    shutil.copytree(DEMO, root)
    app = create_app(
        root,
        docling_check=lambda: True,
        convert_file_func=lambda *a, **k: pytest.fail("converter must not run"),
        upload_dir=tmp_path / "uploads",
    )
    client = TestClient(app)
    response = client.post(
        "/convert",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"]


def test_convert_requires_a_file_or_path(client):
    assert client.post("/convert").status_code == 400
