"""FastAPI app: convert, inspect tables, ask grounded questions.

Run with the demo output (no Docling needed):

    set DOCLING_OUTPUT_DIR=demo\\docs
    python -m uvicorn api.main:app --reload --port 8000

Then open http://127.0.0.1:8000/docs for the interactive OpenAPI page.

Endpoints required by the project:
    POST /convert       upload a file (multipart) and convert it with the engine
    GET  /tables/{id}   one table + its the harness verdict + usability
    POST /ask           grounded answer, or a refusal with the reason

Extra endpoints for the integration/demo:
    POST /convert/path  same conversion, but the file already exists on the server
    GET  /documents     documents, pass counts, chunking method
    GET  /tables        list/filter tables
    POST /validate      re-run the harness on the output folder
    POST /reload        re-scan the output folder after an external conversion
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from harness.validate import validate_directory
from qa.models import Answer, DocumentInfo
from qa.service import QAService

from .convert import convert_file as default_convert_file
from .convert import docling_available as default_docling_available
from .convert import save_upload
from .schemas import (
    AskRequest,
    ConvertRequest,
    ConvertResponse,
    DocumentSummary,
    HealthResponse,
    TableResponse,
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def create_app(
    output_root: str | Path | None = None,
    *,
    prefer_hybrid: bool = True,
    tokenizer: str | None = None,
    convert_file_func=default_convert_file,
    docling_check=default_docling_available,
    upload_dir: str | Path | None = None,
) -> FastAPI:
    """Application factory (tests inject fakes here; production uses the defaults)."""
    root = Path(
        output_root
        or os.getenv("DOCLING_OUTPUT_DIR")
        or "output"
    )
    app = FastAPI(
        title="Docling Document Intelligence API",
        version="1.0.0",
        description=(
            "Chunking, retrieval and grounded Q&A over tables verified by the "
            "deterministic harness. Failed tables are never used to answer."
        ),
    )
    app.state.service = QAService(
        root,
        prefer_hybrid=prefer_hybrid and _env_bool("QA_PREFER_HYBRID", True),
        tokenizer=tokenizer or os.getenv("DOCLING_TOKENIZER"),
        require_totals=_env_bool("QA_REQUIRE_TOTALS", False),
    )
    app.state.output_root = root
    app.state.convert_file = convert_file_func
    app.state.docling_available = docling_check
    app.state.upload_dir = Path(upload_dir or os.getenv("QA_UPLOAD_DIR", "uploads"))

    def service() -> QAService:
        return app.state.service

    def table_response(table_id: str) -> TableResponse:
        context = service().table(table_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"unknown table_id {table_id!r}")
        return TableResponse(
            table=context.table,
            verdict=context.verdict,
            usable=context.verdict.passed,
        )

    def run_conversion(source: Path, accurate: bool, ocr: bool, fallback: bool) -> ConvertResponse:
        if not app.state.docling_available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Docling is not installed. Use `pip install -r requirements.txt`, "
                    "or convert elsewhere and call POST /reload."
                ),
            )
        try:
            summary = app.state.convert_file(
                source, app.state.output_root,
                accurate=accurate, ocr=ocr, fallback=fallback,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - report a clean 500 to the workflow
            raise HTTPException(
                status_code=500,
                detail=f"conversion crashed: {type(exc).__name__}: {exc}",
            ) from exc
        service().reload()
        doc_id = summary.get("doc_id")
        return ConvertResponse(
            summary=summary,
            document=service().document(doc_id) if doc_id else None,
            stats=service().stats(),
        )

    @app.get("/", include_in_schema=False)
    def index():
        return {
            "name": "Docling Document Intelligence API",
            "docs": "/docs",
            "health": "/health",
            "ask": "POST /ask",
        }

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        stats = service().stats()
        return HealthResponse(
            output_root=stats["output_root"],
            docling_available=bool(app.state.docling_available()),
            documents=stats["documents"],
            tables=stats["tables"],
            tables_passed=stats["tables_passed"],
            chunks=stats["chunks"],
            chunking_methods=stats["chunking_methods"],
        )

    @app.get("/documents", response_model=list[DocumentSummary])
    def documents() -> list[DocumentSummary]:
        return [
            DocumentSummary(
                doc_id=info.doc_id,
                status=info.status,
                n_tables=info.n_tables,
                n_passed=info.n_passed,
                pass_rate_tables=info.pass_rate_tables,
                issue=info.issue,
                chunking_method=info.chunking_method,
            )
            for info in service().documents()
        ]

    @app.get("/documents/{doc_id}", response_model=DocumentInfo)
    def document(doc_id: str) -> DocumentInfo:
        info = service().document(doc_id)
        if info is None:
            raise HTTPException(status_code=404, detail=f"unknown doc_id {doc_id!r}")
        return info

    @app.get("/tables", response_model=list[TableResponse])
    def tables(doc_id: str | None = None, passed: bool | None = None):
        return [
            TableResponse(table=context.table, verdict=context.verdict, usable=context.passed)
            for context in service().tables(doc_id=doc_id, passed=passed)
        ]

    @app.get("/tables/{table_id}", response_model=TableResponse)
    def table(table_id: str) -> TableResponse:
        return table_response(table_id)

    @app.post("/ask", response_model=Answer)
    def ask(request: AskRequest) -> Answer:
        return service().ask(
            request.question, doc_id=request.doc_id, top_k=request.top_k
        )

    @app.post("/validate")
    def validate():
        root = app.state.output_root
        if not root.is_dir():
            raise HTTPException(status_code=400, detail=f"output folder not found: {root}")
        summary = validate_directory(
            root,
            tol=service().tol,
            require_totals=service().require_totals,
        )
        return json.loads(summary.model_dump_json())

    @app.post("/reload")
    def reload():
        service().reload()
        return {"reloaded": True, **service().stats()}

    @app.post("/convert", response_model=ConvertResponse)
    def convert(
        file: UploadFile | None = File(default=None),
        path: str | None = Form(default=None),
        accurate: bool = Form(default=False),
        ocr: bool = Form(default=False),
        fallback: bool = Form(default=True),
    ) -> ConvertResponse:
        """Convert an uploaded file, or a server-side path passed as a form field."""
        if file is None and not path:
            raise HTTPException(
                status_code=400, detail="send a multipart `file` or a `path` form field"
            )
        if file is not None:
            suffix = Path(file.filename or "").suffix.lower()
            from engine.convert import SUPPORTED_SUFFIXES
            if suffix not in SUPPORTED_SUFFIXES:
                raise HTTPException(
                    status_code=400,
                    detail=f"unsupported file type {suffix!r}; supported: {sorted(SUPPORTED_SUFFIXES)}",
                )
            source = save_upload(file.file, app.state.upload_dir, file.filename)
        else:
            source = Path(path)  # type: ignore[arg-type]
            if not source.is_file():
                raise HTTPException(status_code=404, detail=f"file not found: {source}")
        return run_conversion(source, accurate, ocr, fallback)

    @app.post("/convert/path", response_model=ConvertResponse)
    def convert_path(request: ConvertRequest) -> ConvertResponse:
        """JSON variant for n8n / watch-folder automation (no multipart)."""
        source = Path(request.path)
        if not source.is_file():
            raise HTTPException(status_code=404, detail=f"file not found: {source}")
        return run_conversion(source, request.accurate, request.ocr, request.fallback)

    return app


app = create_app()
