"""Pydantic v2 models: chunks, verdicts, citations and grounded answers.

The table itself stays in the contract defined by the engine (`engine/contract.py`) and
validated by the harness (`harness/`).  This module only adds the objects needed to chunk,
retrieve and answer from *validated* tables.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from harness.models import TableResult

Cell = int | float | str | None


class ValidationStatus(str, Enum):
    """Validation status attached to every chunk (the gate used by the answerer)."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class Chunk(BaseModel):
    """One retrievable unit.

    A table chunk keeps the *whole* structured table (columns + rows) next to its text,
    so the answerer never has to parse Markdown to recover a number.  Text chunks come
    from the document Markdown (or from Docling's HybridChunker when Docling is installed).
    """

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    doc_id: str
    text: str
    page: int | None = None
    table_id: str | None = None
    kind: Literal["text", "table"] = "text"
    validation_status: ValidationStatus = ValidationStatus.NOT_APPLICABLE
    table_columns: list[str] = Field(default_factory=list)
    table_rows: list[list[Cell]] = Field(default_factory=list)
    part: int = 1
    n_parts: int = 1
    order: int = 0

    @property
    def usable_for_answer(self) -> bool:
        """Only a table whose verdict passed may support a numeric answer."""
        return self.kind == "table" and self.validation_status == ValidationStatus.PASSED


class TableVerdict(BaseModel):
    """the harness verdict, flattened for the API and for chunk metadata."""

    table_id: str
    doc_id: str
    page: int | None = None
    passed: bool
    verifiable: bool = False
    codes: list[str] = Field(default_factory=list)
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.passed


class DocumentInfo(BaseModel):
    """Everything the API knows about one output/<doc_id>/ folder."""

    doc_id: str
    status: Literal["ok", "no_tables", "failed", "unknown"] = "unknown"
    source: str | None = None
    n_tables: int = 0
    n_passed: int = 0
    pass_rate_tables: float | None = None
    issue: str = ""
    chunking_method: str = "none"
    tables: list[TableResult] = Field(default_factory=list)
    verdicts: list[TableVerdict] = Field(default_factory=list)

    @property
    def passed_table_ids(self) -> list[str]:
        return [v.table_id for v in self.verdicts if v.passed]


class Citation(BaseModel):
    """Where an answer comes from.  `row` is 0-based, like the harness failure rows."""

    doc_id: str
    table_id: str
    page: int | None = None
    row: int | None = None
    column: str | None = None
    row_label: str | None = None
    quote: str | None = None


class Answer(BaseModel):
    """The only object returned by POST /ask.

    `refused=True` is a valid, expected answer: it is how the system refuses to answer
    from a table that did not pass verification.
    """

    question: str
    answer: str
    grounded: bool
    refused: bool = False
    reason: str = ""
    method: str = "extractive"
    citations: list[Citation] = Field(default_factory=list)
    used_table_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    """A chunk plus its retrieval score (kept for transparency in tests and slides)."""

    chunk: Chunk
    score: float
    rank: int = 0
