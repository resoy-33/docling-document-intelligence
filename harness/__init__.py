"""Verification harness: deterministic checksum rules on extracted tables (Member 2).

I/O functions live in harness.validate (python -m harness.validate <folder>).
"""
from .checks import DEFAULT_TOL, validate_table
from .models import BatchSummary, DocIssue, Failure, FailureCode, TableResult, ValidationReport

__all__ = [
    "DEFAULT_TOL", "validate_table",
    "BatchSummary", "DocIssue", "Failure", "FailureCode", "TableResult", "ValidationReport",
]
