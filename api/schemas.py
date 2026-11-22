"""Request/response models for the FastAPI app (kept separate for clean OpenAPI docs)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from harness.models import TableResult
from qa.models import Answer, DocumentInfo, TableVerdict


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="Natural-language question")
    doc_id: str | None = Field(default=None, description="Restrict to one document")
    top_k: int = Field(default=5, ge=1, le=20, description="Retrieval depth")

    model_config = {
        "json_schema_extra": {
            "example": {
                "question": "What were Laptops sales in Q1?",
                "doc_id": "sales_2026",
                "top_k": 5,
            }
        }
    }


class DocumentSummary(BaseModel):
    doc_id: str
    status: str
    n_tables: int
    n_passed: int
    pass_rate_tables: float | None = None
    issue: str = ""
    chunking_method: str = "none"


class TableResponse(BaseModel):
    table: TableResult
    verdict: TableVerdict
    usable: bool = Field(description="True only when the harness verdict passed")


class ConvertRequest(BaseModel):
    path: str = Field(description="Local path to a PDF/DOCX/... already on the server")
    accurate: bool = False
    ocr: bool = False
    fallback: bool = True


class ConvertResponse(BaseModel):
    summary: dict
    document: DocumentInfo | None = None
    stats: dict


class HealthResponse(BaseModel):
    status: str = "ok"
    output_root: str
    docling_available: bool
    documents: int
    tables: int
    tables_passed: int
    chunks: int
    chunking_methods: dict[str, str]
    qa_policy: str = (
        "Answers are built only from tables whose harness verdict is passed; "
        "failed tables are refused with a reason."
    )


__all__ = [
    "AskRequest", "Answer", "DocumentSummary", "TableResponse",
    "ConvertRequest", "ConvertResponse", "HealthResponse",
]
