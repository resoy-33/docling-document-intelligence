# harness: deterministic verification of extracted tables

The extraction step (Docling, or the pdfplumber baseline) can silently misread a table.
The harness checks every extracted table with plain arithmetic rules (no AI) and returns a
**pass/fail verdict with the exact reason**. Only tables that pass should be used to answer
questions ("zero hallucination" gate).

```
output/<doc_id>/tables/*.json  ->  TableResult  ->  checksum rules  ->  ValidationReport  ->  pass rates
        (engine, Member 1)         (models.py)       (checks.py)         (models.py)         (validate.py)
```

## Quick start

Run from the project root, with the virtual environment active.

```
python -m harness.validate output                    # Docling results
python -m harness.validate output_baseline           # pdfplumber baseline
python -m harness.validate output --require-totals   # a table with no total counts as a failure
python -m pytest -q                                  # test suite
```

The command prints one line per table, writes `validation_<folder>.json`, and exits with
code 0 if everything passes, 1 otherwise (usable as a gate in a script).

```
PASS  sample_simple_table_p1_t1
FAIL  sample_wrong_total_p1_t1
        - ROW_TOTAL_MISMATCH: row 4 (Total): cells add up to 1250 but 'Total' says 1300
DOC   sample_wrong_total_long_title: NO_TABLES - 0 tables found (...)
```

## Rules

| Rule | Failure code | What it checks |
| --- | --- | --- |
| column count | `COLUMN_COUNT` | every row has exactly `len(columns)` cells |
| empty cells | `EMPTY_CELL` | no `null` or blank cell |
| numeric cells | `NON_NUMERIC` | no text in a numeric column (for example `5O` with a letter O) |
| row totals | `ROW_TOTAL_MISMATCH` | cells of a row add up to its `Total` column |
| column totals | `COLUMN_TOTAL_MISMATCH` | rows of a column add up to the `Total` row |
| totals present | `NO_TOTALS` | only with `--require-totals`: a table with no total cannot be verified |
| file format | `INVALID_FORMAT` | the JSON is unreadable or does not follow the contract |
| document level | `NO_TABLES`, `EXTRACTION_FAILED` | 0 tables found, or the extractor could not read the file |

How totals are found:

- **Total row**: the last row whose first cell is `Total`, `Totale`, `Totaux`, `Somme`, `Sum`, ... (case-insensitive).
- **Total column**: the rightmost column (not the first) whose header is one of those labels.
- A column is numeric if at least half of its non-empty cells are numbers. The first column is the row label and is never summed.
- Tolerance is 0.01 by default (`--tol`), to absorb rounding.

A cell that is empty or text is reported once by its own rule and skipped in the sums,
so one problem does not produce several confusing messages.

## Files

| File | Role |
| --- | --- |
| `models.py` | Pydantic v2 models: `TableResult`, `Failure`, `ValidationReport`, `DocIssue`, `BatchSummary` |
| `checks.py` | the rules and `validate_table()` (pure Python, no file access) |
| `validate.py` | reading files and folders, pass rates, command line |
| `../tests/test_harness.py` | pytest suite (good tables and deliberately corrupted ones) |

## Using it from Python

```python
from harness.validate import validate_file, validate_directory, verified_tables

report = validate_file("output/my_doc/tables/my_doc_p1_t1.json")
report.passed        # True / False
report.failures      # list of Failure(code, message, row, col)
report.verifiable    # True if at least one total could be checked

summary = validate_directory("output")
summary.pass_rate_tables, summary.pass_rate_docs

tables = verified_tables("output")   # ONLY the tables that pass: use these for Q&A
```

## Pass rates: how to read them

- `pass_rate_tables`: share of the tables **found** that pass.
- `pass_rate_docs`: share of the documents that pass. A document with 0 tables or a failed
  extraction counts as a **failure**.
- These rates are **not an accuracy score**. Some sample PDFs contain an error on purpose
  (`sample_wrong_total*.pdf`): the harness failing them is the correct result.

## Limits

- One Total row and one Total column per table; no sub-totals.
- A table with no total is only checked structurally (marked as not verifiable).
- The harness checks that the numbers are *consistent*, not that they match the original PDF.
  A consistent but wrongly read table would pass.
- Percentages and values with units (`12%`, `5 TND`) stay text in the contract, so a numeric
  column containing them is reported as `NON_NUMERIC`.
