"""Pydantic v2 models of the verification harness.

TableResult      a table in the team contract format (what Member 1 writes).
Failure          one reason why a table is rejected.
ValidationReport the pass/fail verdict for ONE table, with every failure reason.
DocIssue         a problem at document level (0 tables found, extraction failed).
BatchSummary     the verdict for a whole output/ folder, including the pass rates.

Design choice: TableResult accepts ragged rows (rows shorter or longer than `columns`).
The harness must be able to LOAD such a table in order to REJECT it with a clear reason;
if Pydantic refused it at load time we would lose the reason.
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field

Cell = int | float | str | None


class TableResult(BaseModel):
    """A table as written by the Docling engine / pdfplumber baseline."""

    model_config = ConfigDict(extra="ignore")

    doc_id: str
    table_id: str
    page: int = Field(ge=0)
    columns: list[str] = Field(min_length=1)
    rows: list[list[Cell]]


class FailureCode(str, Enum):
    # table level
    INVALID_FORMAT = "INVALID_FORMAT"                  # JSON unreadable / not the contract
    COLUMN_COUNT = "COLUMN_COUNT"                      # a row has the wrong number of cells
    EMPTY_CELL = "EMPTY_CELL"                          # null or blank cell
    NON_NUMERIC = "NON_NUMERIC"                        # text inside a numeric column
    ROW_TOTAL_MISMATCH = "ROW_TOTAL_MISMATCH"          # cells of a row do not add up to its Total
    COLUMN_TOTAL_MISMATCH = "COLUMN_TOTAL_MISMATCH"    # cells of a column do not add up to the Total row
    NO_TOTALS = "NO_TOTALS"                            # nothing to verify (only if require_totals)
    # document level
    NO_TABLES = "NO_TABLES"                            # the extractor found 0 tables
    EXTRACTION_FAILED = "EXTRACTION_FAILED"            # the extractor could not read the file


class Failure(BaseModel):
    code: FailureCode
    message: str
    row: int | None = None   # 0-based index in `rows`
    col: int | None = None   # 0-based index in `columns`


class ValidationReport(BaseModel):
    doc_id: str
    table_id: str
    page: int | None = None
    failures: list[Failure] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def passed(self) -> bool:
        return not self.failures

    @computed_field
    @property
    def verifiable(self) -> bool:
        """True if at least one total (row or column) could be checked."""
        return any(c in ("row_totals", "column_totals") for c in self.checks_run)


class DocIssue(BaseModel):
    doc_id: str
    code: FailureCode
    message: str


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


class BatchSummary(BaseModel):
    root: str
    doc_ids: list[str] = Field(default_factory=list)
    reports: list[ValidationReport] = Field(default_factory=list)
    doc_issues: list[DocIssue] = Field(default_factory=list)

    @computed_field
    @property
    def n_tables(self) -> int:
        return len(self.reports)

    @computed_field
    @property
    def n_tables_passed(self) -> int:
        return sum(1 for r in self.reports if r.passed)

    @computed_field
    @property
    def n_docs(self) -> int:
        return len(self.doc_ids)

    @computed_field
    @property
    def n_docs_passed(self) -> int:
        """A document passes if it has >= 1 table, no document issue and every table passes."""
        with_issue = {i.doc_id for i in self.doc_issues}
        n = 0
        for doc_id in self.doc_ids:
            reports = [r for r in self.reports if r.doc_id == doc_id]
            if doc_id not in with_issue and reports and all(r.passed for r in reports):
                n += 1
        return n

    @computed_field
    @property
    def pass_rate_tables(self) -> float | None:
        """Share of the tables FOUND that pass. None if no table was found at all."""
        return _rate(self.n_tables_passed, self.n_tables)

    @computed_field
    @property
    def pass_rate_docs(self) -> float | None:
        """Share of the documents that pass. 0 tables or a failed extraction counts as a failure."""
        return _rate(self.n_docs_passed, self.n_docs)
