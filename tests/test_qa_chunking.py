"""Chunking tests: metadata, verdict status, splitting, fallback behaviour."""
from pathlib import Path

from harness.models import TableResult
from qa.chunking import chunk_markdown, make_table_chunks, table_text
from qa.corpus import load_corpus
from qa.models import Chunk, ValidationStatus

DEMO = Path(__file__).parent.parent / "demo" / "docs"


def test_corpus_loads_demo_with_verdicts():
    corpus = load_corpus(DEMO, prefer_hybrid=False)
    assert set(corpus.documents) == {
        "sales_2026", "regions_2026", "broken_budget", "team_roster", "scanned_report"
    }
    assert corpus.n_tables == 4
    assert corpus.n_passed == 3
    broken = corpus.get_table("broken_budget_p2_t1")
    assert broken is not None and not broken.passed
    assert "ROW_TOTAL_MISMATCH" in broken.verdict.codes
    assert corpus.documents["scanned_report"].issue.startswith("0 tables found")


def test_every_table_chunk_has_page_table_id_and_status():
    corpus = load_corpus(DEMO, prefer_hybrid=False)
    table_chunks = [chunk for chunk in corpus.chunks if chunk.kind == "table"]
    assert table_chunks
    for chunk in table_chunks:
        assert chunk.table_id
        assert chunk.page is not None and chunk.page >= 1
        assert chunk.validation_status in (
            ValidationStatus.PASSED, ValidationStatus.FAILED, ValidationStatus.UNKNOWN
        )
        assert chunk.table_columns
        assert chunk.table_rows
        assert chunk.table_id in chunk.chunk_id


def test_text_chunks_read_page_markers_and_skip_markdown_tables():
    markdown = """
<!-- page: 1 -->
# Title
Some narrative.

| Item | Q1 |
| --- | --- |
| A | 10 |

<!-- page: 2 -->
More narrative on page two.
"""
    chunks = chunk_markdown(markdown, "doc", tables=[], verdicts={})
    assert [chunk.page for chunk in chunks] == [1, 2]
    assert all("| A |" not in chunk.text for chunk in chunks)
    assert "page two" in chunks[1].text


def test_failed_table_is_marked_failed_in_its_chunk():
    corpus = load_corpus(DEMO, prefer_hybrid=False)
    chunk = next(c for c in corpus.chunks if c.table_id == "broken_budget_p2_t1")
    assert chunk.validation_status == ValidationStatus.FAILED
    assert "| Total | 15 | 25 | 99 |" in chunk.text


def test_long_table_split_keeps_same_table_id_and_structured_rows():
    table = TableResult(
        doc_id="d", table_id="d_p1_t1", page=1,
        columns=["Item", "Q1", "Total"],
        rows=[["A", 1, 1], ["B", 2, 2], ["C", 3, 3], ["Total", 6, 6]],
    )
    chunks = make_table_chunks(table, ValidationStatus.PASSED, max_rows_per_chunk=2)
    assert len(chunks) == 2
    assert {chunk.table_id for chunk in chunks} == {"d_p1_t1"}
    assert [chunk.n_parts for chunk in chunks] == [2, 2]
    assert [chunk.part for chunk in chunks] == [1, 2]
    assert sum(len(chunk.table_rows) for chunk in chunks) == 4


def test_table_text_contains_headers_for_retrieval():
    table = TableResult(
        doc_id="d", table_id="d_p1_t1", page=3,
        columns=["Item", "Q1", "Total"], rows=[["A", 10, 10]],
    )
    text = table_text(table, ValidationStatus.PASSED)
    assert "Columns: Item | Q1 | Total" in text
    assert "Validation status: passed" in text
    assert "page 3" in text


def test_chunk_defaults_are_safe():
    chunk = Chunk(chunk_id="x", doc_id="d", text="hello")
    assert chunk.kind == "text"
    assert chunk.validation_status == ValidationStatus.NOT_APPLICABLE
    assert not chunk.usable_for_answer
