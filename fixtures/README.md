# Fixtures (hand-written tables in the team contract format)

| File | What it is | Expected verdict (harness) |
|---|---|---|
| good_table_1.json | correct totals | pass |
| good_table_2.json | correct totals | pass |
| wrong_total.json | grand total is 99 instead of 40 | fail: wrong total |
| missing_cell.json | one empty cell | fail: missing cell |
| ragged_columns.json | a row with fewer cells than columns | fail: column count |

the harness, the Q&A layer and the automation build against these until real Docling output is available.
