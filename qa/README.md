# Chunking, retrieval and grounded Q&A (`qa/`)

This folder turns verified tables into retrievable chunks, retrieves the right evidence for
a question, and answers **only** from tables whose harness verdict is `passed: true`.
A failed table is never used to answer, even if it is the best lexical match.

```
output/<doc_id>/tables/*.json ──> harness.validate_file ──> TableVerdict (passed/failed)
             │                                                   │
             ├── .md / .docling.json ──> chunker ──> Chunk(page, table_id, validation_status)
             │                                                   │
             └──────────────────────────────> BM25 retrieval <───┘
                                                        │
question ─────────────────────────────────────────> grounded answerer
                                                        │
                              Answer(grounded, citations, refused, warnings)
```

## Quick start (no Docling download)

From the project root:

```bat
.venv\Scripts\activate.bat
python demo\make_demo.py
python -m qa.demo --root demo/docs --list
python -m qa.demo --root demo/docs --question "What were Laptops sales in Q1?"
```

Expected shape of the last command:

```json
{
  "question": "What were Laptops sales in Q1?",
  "answer": "Laptops, Q1: 120.\nSource: sales_2026, page 1, table sales_2026_p1_t1.",
  "grounded": true,
  "refused": false,
  "citations": [{"doc_id": "sales_2026", "page": 1, "table_id": "sales_2026_p1_t1", "row_label": "Laptops", "column": "Q1"}],
  "used_table_ids": ["sales_2026_p1_t1"]
}
```

Ask about the deliberately broken table:

```bat
python -m qa.demo --root demo/docs --question "What is the total in the broken budget?"
```

It exits with code 3 and returns `refused: true`, the table id, and the harness reason
(`ROW_TOTAL_MISMATCH` / `COLUMN_TOTAL_MISMATCH`). That refusal is the feature.

## Files

| File | Role |
|---|---|
| `models.py` | Pydantic v2 models: `Chunk`, `TableVerdict`, `Citation`, `Answer` |
| `verdicts.py` | recomputes the harness verdict with `harness.validate_file` (never trusts a stale JSON report) |
| `chunking.py` | HybridChunker path + deterministic Markdown/table fallback |
| `retrieval.py` | dependency-free BM25 index with accent folding and small plural folding |
| `corpus.py` | scans `output/<doc_id>/`, loads tables, verdicts, chunks and document issues |
| `answer.py` | extractive grounded answerer, refusal policy, number-grounding check, optional LLM gate |
| `service.py` | `QAService` used by FastAPI and the CLI |
| `demo.py` | command-line demo |

## Chunking

Every chunk carries the metadata required by the plan: `page`, `table_id` and
`validation_status`.

| Strategy | When it runs | What it produces |
|---|---|---|
| **HybridChunker** (`docling.chunking.HybridChunker`) | `docling` is installed **and** `<doc_id>.docling.json` exists | Docling chunks, with page provenance and table references mapped back to the engine's `table_id` |
| **Markdown/table fallback** | Docling missing, JSON unreadable, or HybridChunker returns nothing | text chunks from `<doc_id>.md` + one structured chunk per contract table |

The fallback is not pretending to be HybridChunker: `GET /health` and
`GET /documents` expose `chunking_method` (`"hybrid"` or `"markdown (...)"`).

Fallback page numbers:

* table chunks always take `page` from the contract JSON;
* text chunks read `<!-- page: N -->` markers when the Markdown contains them;
* otherwise `page` is `None` — we never invent a page number.

Table chunks carry `table_columns` and `table_rows` in addition to their text. The
answerer uses those structured fields, not the Markdown, so a mis-parsed Markdown table
cannot change a number. Long tables are split into parts that keep the same `table_id`;
aggregation still loads the full contract table from disk.

## Retrieval

`retrieval.BM25Index` is a deterministic BM25 implementation (no model download, no API
key). It folds accents (`Catégorie` = `categorie`) and folds simple plurals
(`laptops` = `laptop`). Table chunks get a 10% tie-break boost because they contain both
row labels and column headers. The answerer also scores row/column matches directly, so a
question like "Laptops Q1" does not depend on BM25 alone.

An embedding backend is a drop-in extension, but it is **not** enabled by default: this
project values deterministic, reproducible evidence over a model that may rank a failed
table first.

## Answer policy (zero hallucination)

1. Compute a verdict for every table with the harness.
2. If the best-matching table failed, **refuse** and show the failure reason. Do not switch
   to a weaker passing table that would silently change the subject.
3. Only use `passed` tables. If a table is passed but has no totals, answer and attach a
   warning that only its structure was verified.
4. Build the answer extractively from cells/rows/columns; add
   `Source: <doc_id>, page <P>, table <table_id>`.
5. Verify every number in the answer body against the table values (plus numbers the
   deterministic path computed). If the check fails, refuse rather than emit it.

Supported question shapes:

| Question | Behaviour |
|---|---|
| `What were Laptops sales in Q1?` | exact cell + citation |
| `What is the total for Phones?` | row total |
| `What is the total in Q1?` | validated Total-row cell |
| `What is the grand total in the sales report?` | grand total |
| `What is the sum of Q1 across products?` | computed sum (or validated Total-row value) |
| `What is the average of Q1?` | computed average |
| `Which product sold the most in Q1?` | max with row label |
| `Which region had the highest January sales?` | month alias + max |
| `Compare Laptops and Phones` | multi-row comparison |
| `How many rows does the table have?` | deterministic count |
| `Show the sales table` | table summary |
| `What is the total in the broken budget?` | **refused** with harness reason |
| `What does the scanned report say?` | **refused**: 0 tables is a failure |
| `What is the weather?` | **refused**: no matching validated evidence |

Refusal is returned as HTTP 200 by `POST /ask` with `refused: true`. It is a valid answer,
not a server error.

## Optional LLM (off by default)

`answer_question(..., llm=callable)` accepts any function `prompt -> text`. The prompt
contains only the validated table. The LLM output is accepted only if every number in it
passes the same grounding check; otherwise the extractive answer is returned and the
rejection is recorded in `warnings`. Tests use a fake "lying" LLM to prove the gate works.
The API does not configure a provider by default: there is no API key and no untested
network call in the deliverable.

## Tests

```bat
python -m pytest -q tests\test_qa_chunking.py tests\test_qa_answer.py tests\test_api.py
```

The Q&A tests cover chunk metadata, page markers, failed-table status, table
splitting, every answer shape above, every refusal path, the number-grounding check, the
fake-LLM rejection, the API endpoints, and `/convert` with a fake engine.

Last run (Python 3.12, Docling not installed):
`127 passed, 2 skipped` for the **whole project** suite. The 2 skipped tests are the
Docling-only tests from the engine; the HybridChunker path therefore has **not** been
executed on this machine. It is implemented and will run once Docling is installed.

## Limits (state these on the slides)

* The hybrid path is implemented but not executed here; the verified local path is the
  Markdown fallback.
* BM25 is lexical: synonyms not present in the table are not understood.
* The answerer supports one Total row / one Total column, like the harness.
* Text chunks are retrieved for context but are **not** a source of numeric answers.
* The harness checks arithmetic consistency, not agreement with the original PDF. A
  consistently misread table can pass; that is a documented limit of the harness, not hidden.
* No authentication, rate limiting or multi-user storage: this is a local academic demo.

## Sources for the slides

* Docling documentation — https://docling-project.github.io/docling/
* Docling chunking concepts — https://docling-project.github.io/docling/concepts/chunking/
* Docling paper (arXiv:2408.09869) — https://arxiv.org/abs/2408.09869
* RAG (Lewis et al., 2020) — https://arxiv.org/abs/2005.11401
* BM25 (Robertson & Zaragoza, 2009) — https://doi.org/10.1561/1500000019
* FastAPI — https://fastapi.tiangolo.com/
* Pydantic v2 — https://docs.pydantic.dev/latest/
