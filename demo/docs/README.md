# Demo output (hand-written, not Docling)

Hand-written demo data for the API/Q&A tests. Not produced by Docling. Real engine output comes from `python -m engine.convert samples --out output`.

| Document | Status | Table | Expected verdict |
|---|---|---|---|
| `sales_2026` | ok | `sales_2026_p1_t1` | PASS (valid totals) |
| `regions_2026` | ok | `regions_2026_p1_t1` | PASS (valid totals) |
| `team_roster` | ok | `team_roster_p1_t1` | PASS structurally, not verifiable (no totals) |
| `broken_budget` | ok | `broken_budget_p1_t1` | FAIL (Total 99 instead of 40) |
| `scanned_report` | no_tables | none | document-level failure, Q&A must refuse |

Regenerate with `python demo/make_demo.py`.  For real output, run
`python -m engine.convert samples --out output` and point the API at `output/`.
