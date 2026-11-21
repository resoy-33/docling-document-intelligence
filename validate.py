"""Read table JSON files, validate them, compute the pass rate.

    python -m harness.validate output                    # Docling results
    python -m harness.validate output_baseline           # pdfplumber baseline
    python -m harness.validate output --require-totals   # a table with no total counts as a failure

Writes validation_<folder>.json (full report) and prints one line per table.
Exit code: 0 if everything passes, 1 otherwise (usable as a gate in a script).

Rules that matter for the benchmark:
  - a document with 0 tables, or whose extraction failed (summary.json), is a FAILURE;
  - the pass rate is given per table (found tables only) and per document (strict).
Member 3 can call verified_tables(root) to get ONLY the tables that passed.
"""
import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .checks import DEFAULT_TOL, validate_table
from .models import BatchSummary, DocIssue, Failure, FailureCode, TableResult, ValidationReport


def load_table(path: Path) -> TableResult:
    return TableResult.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'table'}: {e['msg']}" for e in exc.errors()[:3]
        )
    return f"{type(exc).__name__}: {exc}"


def validate_file(
    path: Path, tol: float = DEFAULT_TOL, require_totals: bool = False
) -> ValidationReport:
    """Validate one table JSON file. Never raises: an unreadable file is a failed verdict."""
    path = Path(path)
    try:
        table = load_table(path)
    except (OSError, ValueError) as exc:  # json errors and pydantic ValidationError are ValueError
        doc_id = path.parent.parent.name if path.parent.name == "tables" else path.parent.name
        return ValidationReport(
            doc_id=doc_id,
            table_id=path.stem,
            failures=[Failure(code=FailureCode.INVALID_FORMAT,
                              message=f"not a valid table file: {_describe(exc)}")],
            checks_run=["format"],
        )
    return validate_table(table, tol=tol, require_totals=require_totals)


def validate_directory(
    root: Path, tol: float = DEFAULT_TOL, require_totals: bool = False
) -> BatchSummary:
    """Validate every output/<doc_id>/tables/*.json produced by the engine."""
    root = Path(root)
    summary = BatchSummary(root=str(root))
    for doc_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        summary_path = doc_dir / "summary.json"
        tables_dir = doc_dir / "tables"
        if not summary_path.exists() and not tables_dir.exists():
            continue  # not a document folder
        doc_id = doc_dir.name
        summary.doc_ids.append(doc_id)

        status, error = None, None
        if summary_path.exists():
            try:
                info = json.loads(summary_path.read_text(encoding="utf-8"))
                status, error = info.get("status"), info.get("error")
            except (OSError, ValueError):
                status = None

        files = sorted(tables_dir.glob("*.json")) if tables_dir.exists() else []
        if status == "failed":
            summary.doc_issues.append(DocIssue(
                doc_id=doc_id, code=FailureCode.EXTRACTION_FAILED,
                message=f"extraction failed: {error or 'unknown error'}"))
        elif not files:
            summary.doc_issues.append(DocIssue(
                doc_id=doc_id, code=FailureCode.NO_TABLES,
                message="0 tables found (a table was expected: treated as a failure)"))
        for f in files:
            summary.reports.append(validate_file(f, tol=tol, require_totals=require_totals))
    return summary


def verified_tables(
    root: Path, tol: float = DEFAULT_TOL, require_totals: bool = False
) -> list[TableResult]:
    """Only the tables that PASS the harness. This is what the Q&A step (Member 3) may use."""
    tables = []
    for path in sorted(Path(root).glob("*/tables/*.json")):
        if validate_file(path, tol=tol, require_totals=require_totals).passed:
            tables.append(load_table(path))
    return tables


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.1f}%"


def print_summary(summary: BatchSummary) -> None:
    for r in summary.reports:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.table_id}"
              f"{'' if r.verifiable or not r.passed else '  (no total to verify)'}")
        for f in r.failures:
            print(f"        - {f.code.value}: {f.message}")
    for issue in summary.doc_issues:
        print(f"DOC   {issue.doc_id}: {issue.code.value} - {issue.message}")
    print(f"\nTables   : {summary.n_tables_passed}/{summary.n_tables} pass "
          f"({_pct(summary.pass_rate_tables)})")
    print(f"Documents: {summary.n_docs_passed}/{summary.n_docs} pass "
          f"({_pct(summary.pass_rate_docs)})  [0 tables or failed extraction = failure]")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verification harness: checksum rules on extracted tables")
    ap.add_argument("root", help="output folder of the engine (e.g. output or output_baseline)")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL, help="absolute tolerance (default 0.01)")
    ap.add_argument("--require-totals", action="store_true",
                    help="fail tables that have no Total row/column (nothing to verify)")
    ap.add_argument("--out", help="JSON report path (default: validation_<folder>.json)")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        raise SystemExit(f"Not a folder: {root}")
    summary = validate_directory(root, tol=args.tol, require_totals=args.require_totals)
    print_summary(summary)

    out = Path(args.out) if args.out else Path(f"validation_{root.name}.json")
    out.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    print(f"(saved to {out})")
    ok = summary.n_tables_passed == summary.n_tables and not summary.doc_issues
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
