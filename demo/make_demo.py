"""Generate `demo/docs/`, a hand-written engine-output folder for demos and tests.

This is NOT Docling output and must never be presented as such.  It exists so the API,
chunking, retrieval, refusal and tests can run on a machine without the Docling models.
Real output is produced by:

    python -m engine.convert samples --out output

Run from the project root:

    python demo/make_demo.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "docs"

NOTE = (
    "Hand-written demo data for the API/Q&A tests. Not produced by Docling. "
    "Real engine output comes from `python -m engine.convert samples --out output`."
)


def table(doc_id: str, page: int, columns: list[str], rows: list[list]) -> dict:
    return {
        "doc_id": doc_id,
        "table_id": f"{doc_id}_p{page}_t1",
        "page": page,
        "columns": columns,
        "rows": rows,
    }


def write_doc(
    doc_id: str,
    status: str,
    tables: list[dict],
    markdown: str,
    page: int = 1,
    warning: str | None = None,
    error: str | None = None,
):
    folder = ROOT / doc_id
    (folder / "tables").mkdir(parents=True, exist_ok=True)
    for item in tables:
        (folder / "tables" / f"{item['table_id']}.json").write_text(
            json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    (folder / f"{doc_id}.md").write_text(markdown.strip() + "\n", encoding="utf-8")
    summary = {
        "doc_id": doc_id,
        "source": f"demo/{doc_id}.pdf",
        "status": status,
        "seconds": 0.0,
        "n_tables": len(tables),
        "table_ids": [item["table_id"] for item in tables],
        "note": NOTE,
    }
    if warning:
        summary["warning"] = warning
    if error:
        summary["error"] = error
    (folder / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> int:
    if ROOT.exists():
        # Only remove the generated document folders, keep any README a human added.
        for child in ROOT.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
    ROOT.mkdir(parents=True, exist_ok=True)

    sales = table(
        "sales_2026", 1,
        ["Item", "Q1", "Q2", "Q3", "Total"],
        [
            ["Laptops", 120, 135, 150, 405],
            ["Phones", 200, 180, 220, 600],
            ["Tablets", 80, 95, 70, 245],
            ["Total", 400, 410, 440, 1250],
        ],
    )
    write_doc(
        "sales_2026", "ok", [sales],
        """
<!-- page: 1 -->
# 2026 Sales Review

This synthetic report is used only to demonstrate the chunking and grounded Q&A.
The quarterly table is stored as a contract table in `tables/`.

<!-- page: 2 -->
## How to read the numbers

The Total row is the arithmetic check used by the verification harness.  A question about
a product or a quarter must be answered from this validated table, with a page and table
citation.
""",
    )

    regions = table(
        "regions_2026", 1,
        ["Region", "Jan", "Feb", "Mar", "Total"],
        [
            ["North", 100, 110, 120, 330],
            ["South", 90, 95, 100, 285],
            ["Total", 190, 205, 220, 615],
        ],
    )
    write_doc(
        "regions_2026", "ok", [regions],
        """
<!-- page: 1 -->
# Regional performance

A second synthetic report, deliberately shaped like a Docling extraction: one table with
month headers and a validated Total row.  It lets the demo ask month questions (January)
as well as quarter questions.
""",
    )

    broken = table(
        "broken_budget", 2,
        ["Item", "Q1", "Q2", "Total"],
        [
            ["A", 10, 20, 30],
            ["B", 5, 5, 10],
            ["Total", 15, 25, 99],
        ],
    )
    write_doc(
        "broken_budget", "ok", [broken],
        """
<!-- page: 2 -->
# Budget with a deliberate error

This table is intentionally corrupted: the Total column says 99 while 30 + 10 = 40.
the harness must fail it, and the Q&A layer must refuse to answer from it.
""",
    )

    roster = table(
        "team_roster", 1,
        ["Name", "Age", "City"],
        [
            ["Ali", 30, "Tunis"],
            ["Sara", 29, "Sfax"],
            ["Mouna", 34, "Sousse"],
        ],
    )
    write_doc(
        "team_roster", "ok", [roster],
        """
<!-- page: 1 -->
# Team roster

This table has no Total row or column.  The harness can only verify its structure, so the
answerer must still work but attach a "not verifiable" warning.
""",
    )

    write_doc(
        "scanned_report", "no_tables", [],
        """
<!-- page: 1 -->
# Scanned report

This document simulates a scanned PDF for which Docling found 0 tables.  It exists to test
the refusal path: a document with 0 tables where one is expected is a failure, not a pass.
""",
        warning=(
            "0 tables found. If this document should contain a table, treat this as a FAILURE "
            "(Docling's layout model can miss or mislabel a table)."
        ),
    )

    (ROOT / "README.md").write_text(
        f"""# Demo output (hand-written, not Docling)

{NOTE}

| Document | Status | Table | Expected verdict |
|---|---|---|---|
| `sales_2026` | ok | `sales_2026_p1_t1` | PASS (valid totals) |
| `regions_2026` | ok | `regions_2026_p1_t1` | PASS (valid totals) |
| `team_roster` | ok | `team_roster_p1_t1` | PASS structurally, not verifiable (no totals) |
| `broken_budget` | ok | `broken_budget_p1_t1` | FAIL (Total 99 instead of 40) |
| `scanned_report` | no_tables | none | document-level failure, Q&A must refuse |

Regenerate with `python demo/make_demo.py`.  For real output, run
`python -m engine.convert samples --out output` and point the API at `output/`.
""",
        encoding="utf-8",
    )
    print(f"Wrote {ROOT} ({len(list(ROOT.iterdir()))} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
