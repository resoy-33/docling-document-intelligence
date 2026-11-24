"""Bridge between the harness and the Q&A layer.

Important design choice: the verdict is always **recomputed** with the deterministic
harness (`harness.validate_file`) instead of trusting a saved JSON report.  A saved
`validation_output.json` can be outdated; the checksum is cheap, so we run it again.
"""
from __future__ import annotations

from pathlib import Path

from harness.checks import DEFAULT_TOL
from harness.models import ValidationReport
from harness.validate import validate_file

from .models import TableVerdict


def verdict_from_report(report: ValidationReport) -> TableVerdict:
    """Turn a harness ValidationReport into the small object the API exposes."""
    codes = [failure.code.value for failure in report.failures]
    reason = "; ".join(f"{f.code.value}: {f.message}" for f in report.failures)
    return TableVerdict(
        table_id=report.table_id,
        doc_id=report.doc_id,
        page=report.page,
        passed=report.passed,
        verifiable=report.verifiable,
        codes=codes,
        reason=reason,
        warnings=list(report.warnings),
    )


def verdict_for_file(
    path: Path, tol: float = DEFAULT_TOL, require_totals: bool = False
) -> TableVerdict:
    """Validate one table JSON file and return the verdict (never raises)."""
    return verdict_from_report(
        validate_file(path, tol=tol, require_totals=require_totals)
    )
