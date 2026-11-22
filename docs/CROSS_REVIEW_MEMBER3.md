# Cross-review by Member 3 — engine (Member 1) and harness (Member 2)

Date: 2026-11-22. Reviewer scope: `engine/`, `fixtures/`, `samples/`, `harness/`, `tests/`,
`README.md`, `run_all.bat`, `setup_windows.bat`, `requirements.txt`.
Method: read the code, ran the test suite, ran the CLI on the committed demo corpus, and
exercised the API against hand-written output. No Docling model was installed on this
machine, so Docling-only paths were not executed (they are marked below).

## Verification log

| Command | Result |
|---|---|
| `python -m pytest -q` before Member 3 work | **72 passed, 2 skipped** (Docling not installed) |
| `python -m pytest -q` after Member 3 work | **119 passed, 2 skipped** |
| `python -m qa.demo --root demo/docs --list` | 5 documents, 4 tables, 3 pass |
| `python -m qa.demo ... "What were Laptops sales in Q1?"` | `120`, page 1, table citation |
| `python -m qa.demo ... "What is the total in the broken budget?"` | refused with `ROW_TOTAL_MISMATCH` / `COLUMN_TOTAL_MISMATCH` |
| uvicorn `127.0.0.1:8010` | `/health`, `/ask`, `/tables/{id}`, `/validate`, `/openapi.json` all HTTP 200 |

The "2 skipped" are Member 1's real-Docling tests (`test_real_docling_reads_an_excel_file`,
`test_real_docling_isolates_a_corrupt_file`). They are not failures; they skip cleanly.

## Member 1 — engine

### What is good

* Clear separation: `engine/contract.py` is pure pandas, `engine/convert.py` owns Docling.
  The contract matches the PDF exactly (`doc_id`, `table_id`, `page`, `columns`, `rows`).
* Strong operational thinking: per-file failure isolation, `run_report.json`, exit code 2,
  retry cascade (fast → accurate → OCR+accurate → optional VLM), no overwriting of a good
  attempt with a later empty one.
* Number cleaning is unusually thorough for a student project: US/EU grouping, space
  grouping, parentheses negatives, currency, percentages deliberately left as text.
* Honest README status table, including the real failure
  (`sample_wrong_total_long_title.pdf` → 0 tables) and the untested VLM path.
* Tests use fake converters, so the engine logic is testable without the models.

### Findings

| # | Severity | Finding | Evidence / recommendation |
|---|---|---|---|
| 1 | Medium | `process_file()` calls `write_outputs()` **outside** the retry `try`. If `export_to_markdown()`, `export_to_dict()` or `export_to_dataframe()` raises for one file, the whole batch run aborts. | `engine/convert.py`, `process_file` after `best` selection. Wrap `write_outputs` in `try/except`, write a `failed` summary, continue. Member 3's API catches this at HTTP boundary, but the CLI does not. |
| 2 | Medium | Root README claimed "55 pytest tests"; the actual baseline was 72 passed + 2 skipped. | Stale claim. Fixed in this branch; the number is now generated from a real run. Keep it that way. |
| 3 | Medium | A fresh clone has no `output/` (git-ignored), so the Member 3 API/Q&A could not be demonstrated without a 5 GB Docling install. | Added a clearly labelled hand-written `demo/docs/` + `requirements-api.txt`. It is **not** Docling output and says so. |
| 4 | Low | `run_all.bat` stops after conversion and the baseline comparison; it never calls Member 2's harness. | Add `python -m harness.validate output` and `python -m harness.validate output_baseline` as a final step, or make a combined `run_pipeline.bat`. This is the missing integration link in the "dependency at a glance" chain. |
| 5 | Low | Missing Docling is hidden as `status: "failed"` because `process_file` catches every exception, including `ImportError`. | The API checks `find_spec("docling")` first and returns a clear HTTP 503. Consider a dedicated `dependency` status in the engine. |
| 6 | Low | `--vlm` / `build_vlm_converter()` is untested and references `VlmPipelineOptions`, which is version-sensitive. | README says untested (good). Do not put it in the demo path; have a fallback message if the class changes. |
| 7 | Low | The `.docling.json` is written with `doc.export_to_dict()`; reloadability is not tested. | Member 3's HybridChunker path uses `DoclingDocument.model_validate_json` and falls back if it fails. Test the reload once Docling is installed. |
| 8 | Info | `sample_wrong_total_long_title.pdf` gives 0 tables; cause unknown. | Keep it as the honest failure case. Do not "fix" the sample to make the matrix look better. |

## Member 2 — verification harness

### What is good

* The rules match the professor's requirement: row sums, column sums, empty cells, column
  count, numeric-cell check, clear failure codes and messages with row/column indexes.
* Pydantic v2 models are well chosen: ragged rows are accepted at load time so the harness
  can reject them with a reason instead of losing the error at validation time.
* Pass rates are defined twice (tables found vs documents), and 0 tables / failed extraction
  are counted as document failures — exactly what the plan asks.
* Tests are ground-truth driven: two good fixtures pass, three broken fixtures fail for the
  right reason. The `verified_tables()` helper is a clean hand-off to Member 3.
* Limits are documented (one Total row/column, structural-only tables, consistency ≠
  agreement with the PDF).

### Findings

| # | Severity | Finding | Evidence / recommendation |
|---|---|---|---|
| 1 | Medium | Any blank cell fails the table, including a blank text cell in a Total row. Real Docling output often has merged/blank label cells, so good tables may be rejected. | `check_empty_cells` is unconditional. This is a deliberate strict choice, but document it on the slides and consider a `--allow-empty-text` option for non-numeric columns. Do not loosen the numeric columns. |
| 2 | Low | `validate_directory(root)` raises `FileNotFoundError` if `root` does not exist. | The API guards this with `root.is_dir()` before calling. A CLI user gets a traceback instead of a clean message; catch it and exit 2. |
| 3 | Low | `find_total_row` only looks at the first cell; `find_total_col` only at the rightmost total header. Tables with "Grand Total" in another column are not verified. | Documented as a limit. Fine for the sample set; mention it when comparing with TEDS. |
| 4 | Low | A table with no totals is `passed=True, verifiable=False`; a caller that only checks `passed` may treat it as fully verified. | Member 3 now attaches a warning for exactly this case. Keep `verifiable` in the API response. |
| 5 | Info | The harness checks arithmetic consistency, not fidelity to the source PDF. A consistently misread table can pass. | Already documented. Say it explicitly in the demo: the harness is a consistency gate, not an OCR oracle. |
| 6 | Info | `pass_rate_tables` counts only tables found; a document with 0 tables does not enter that denominator. | `pass_rate_docs` covers it. Report both numbers; never report only the table rate. |

## Integration fixes made by Member 3

* Added a light install path (`requirements-api.txt`, `setup_member3.bat`) so the API/Q&A
  can be tested without Docling.
* Added `demo/docs/` with 5 documents / 4 tables: 3 pass, 1 fails its checksum, 1 has 0
  tables. This exercises both the answer path and both refusal paths.
* Added `qa/` and `api/` implementations with 47 tests, all green.
* Recomputed Member 2's verdict inside the Q&A service (`harness.validate_file`) instead of
  trusting a saved report; a stale verdict can never unlock a failed table.
* Exposed `chunking_method` and `docling_available` in `/health`, so the demo cannot
  accidentally claim HybridChunker ran when the fallback ran.
* Updated the README test claim and added the honest Member 3 status rows.

## Remaining risks for the final demo

1. **HybridChunker has not run on this machine.** Install Docling, run the engine, verify
   `/health` says `hybrid`, and re-run the suite before claiming it in the video.
2. **No real Docling table has gone through the API yet.** Use `output/` from Member 1 and
   ask at least one cell question and one refusal question. Record the result, even if the
   pass rate is low.
3. **The demo corpus is synthetic.** Never present it as Docling output; use it to explain
   the API and refusal policy, then switch to `output/` for the real result.
4. **One bad table can abort the CLI batch** (Member 1 finding #1). Keep an output folder
   from a previous run; do not re-run the engine live during the demo without a backup.
5. **Empty-cell strictness** may reject real tables. Report the pass rate honestly and
   show one rejected table with its reason rather than hiding it.

## Suggested division for the live Q&A

* Member 1: pipeline, Docling/TableFormer, retry cascade, comparison matrix.
* Member 2: checksum rules, why a table can look plausible and still be wrong, TEDS.
* Member 3: chunk metadata, retrieval, refusal policy, citation, FastAPI/OpenAPI.
* Member 4: watch-folder/n8n, sequence diagram, packaging, demo video.

Every claim above is backed by a command in the verification log or by a file/line
reference in this repository. Claims about Docling-only paths are marked as not executed.
