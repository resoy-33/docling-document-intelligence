"""the Q&A layer grounded Q&A tests.

The most important tests are the refusal tests: a table that fails the harness must never
support an answer, and an answer must never contain a number that is not in its cited
table (or computed from it by the deterministic path).
"""
from pathlib import Path

import pytest

from qa.answer import (
    answer_question,
    numbers_in_text,
    verify_grounding,
)
from qa.corpus import load_corpus

DEMO = Path(__file__).parent.parent / "demo" / "docs"


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(DEMO, prefer_hybrid=False)


def ask(corpus, question: str, **kwargs):
    return answer_question(question, corpus, **kwargs)


# ------------------------------------------------------------------ good answers
def test_cell_lookup_is_grounded_and_cited(corpus):
    answer = ask(corpus, "What were Laptops sales in Q1?")
    assert not answer.refused and answer.grounded
    assert "120" in answer.answer
    assert answer.used_table_ids == ["sales_2026_p1_t1"]
    citation = answer.citations[0]
    assert (citation.doc_id, citation.page, citation.table_id) == (
        "sales_2026", 1, "sales_2026_p1_t1"
    )
    assert citation.row_label == "Laptops" and citation.column == "Q1"


def test_row_total(corpus):
    answer = ask(corpus, "What is the total for Phones?")
    assert "600" in answer.answer
    assert "Total" in answer.answer


def test_grand_total(corpus):
    answer = ask(corpus, "What is the grand total in the sales report?")
    assert "1250" in answer.answer


def test_column_total_uses_the_validated_total_row(corpus):
    answer = ask(corpus, "What is the total in Q1?")
    assert "400" in answer.answer
    assert "validated Total row" in answer.answer


def test_sum_over_a_column(corpus):
    answer = ask(corpus, "What is the sum of Q1 across products?")
    assert "400" in answer.answer


def test_average_is_computed_and_grounded(corpus):
    answer = ask(corpus, "What is the average of Q1?")
    assert answer.grounded and "133.33" in answer.answer


def test_max_uses_row_labels(corpus):
    answer = ask(corpus, "Which product sold the most in Q1?")
    assert "Phones" in answer.answer and "200" in answer.answer


def test_count(corpus):
    answer = ask(corpus, "How many rows does the sales table have?")
    assert "3 data rows" in answer.answer


def test_compare_two_rows(corpus):
    answer = ask(corpus, "Compare Laptops and Phones")
    assert "405" in answer.answer and "600" in answer.answer


def test_month_alias(corpus):
    answer = ask(corpus, "Which region had the highest January sales?")
    assert "North" in answer.answer and "100" in answer.answer


def test_show_table(corpus):
    answer = ask(corpus, "Show the sales table", doc_id="sales_2026")
    assert not answer.refused
    assert "| Laptops | 120 | 135 | 150 | 405 |" in answer.answer


def test_table_without_totals_warns_but_answers(corpus):
    answer = ask(corpus, "How old is Sara?")
    assert not answer.refused and "29" in answer.answer
    assert any("no Total row/column" in warning for warning in answer.warnings)


# ------------------------------------------------------------------- refusals
def test_failed_table_is_refused_with_the_reason(corpus):
    answer = ask(corpus, "What is the total in the broken budget?")
    assert answer.refused and not answer.grounded
    assert "broken_budget_p2_t1" in answer.used_table_ids
    assert any("ROW_TOTAL_MISMATCH" in warning for warning in answer.warnings)
    assert "99" not in answer.answer.split("Source:")[0]


def test_document_with_zero_tables_is_refused(corpus):
    answer = ask(corpus, "What does the scanned report say?", doc_id="scanned_report")
    assert answer.refused
    assert "0 tables" in answer.reason


def test_unknown_document_is_refused(corpus):
    answer = ask(corpus, "What is the total?", doc_id="does_not_exist")
    assert answer.refused and "unknown document" in answer.reason


def test_irrelevant_question_is_refused(corpus):
    answer = ask(corpus, "What is the weather in Paris?")
    assert answer.refused
    assert "no validated table" in answer.reason


def test_empty_question_is_refused(corpus):
    answer = ask(corpus, "   ")
    assert answer.refused


def test_a_failed_table_does_not_get_answered_from_another_table(corpus):
    # "budget" names the failed document, so the failure must win even though the sales
    # table also has a Total row.
    answer = ask(corpus, "What is the total in the budget?")
    assert answer.refused
    assert "broken_budget_p2_t1" in answer.used_table_ids


def test_refusal_still_lists_retrieved_chunks(corpus):
    answer = ask(corpus, "What is the total in the broken budget?")
    assert answer.retrieved_chunk_ids


# ----------------------------------------------------------------- grounding
def test_verify_grounding_accepts_table_numbers():
    allowed = {120.0, 135.0, 405.0}
    assert verify_grounding("Laptops Q1: 120 and Q2: 135 (total 405).", allowed) == []


def test_verify_grounding_rejects_hallucinated_number():
    assert verify_grounding("Laptops Q1 was 999.", {120.0}) == [999.0]


def test_numbers_in_text_ignores_identifiers_and_column_names():
    # Q1, p1_t1 and sales_2026 are identifiers, not values.
    assert numbers_in_text("Q1 in sales_2026_p1_t1 is 120") == [120.0]


def test_good_answer_body_only_contains_table_values(corpus):
    answer = ask(corpus, "What were Laptops sales in Q1?")
    body = answer.answer.split("Source:")[0]
    table = corpus.get_table("sales_2026_p1_t1").table
    allowed = {float(cell) for row in table.rows for cell in row if isinstance(cell, (int, float))}
    assert verify_grounding(body, allowed) == []


# --------------------------------------------------------------- optional LLM
def test_llm_answer_accepted_when_grounded(corpus):
    def grounded_llm(prompt: str) -> str:
        assert "validated" in prompt
        return "Laptops sold 120 units in Q1."

    answer = ask(corpus, "What were Laptops sales in Q1?", llm=grounded_llm)
    assert answer.method == "llm+grounding-check"
    assert not answer.refused and "120" in answer.answer


def test_llm_hallucination_is_rejected_and_falls_back(corpus):
    def lying_llm(prompt: str) -> str:
        return "Laptops sold 999 units in Q1."

    answer = ask(corpus, "What were Laptops sales in Q1?", llm=lying_llm)
    assert answer.method == "extractive"
    assert "999" not in answer.answer
    assert "120" in answer.answer
    assert any("rejected by the grounding check" in warning for warning in answer.warnings)


def test_llm_exception_falls_back(corpus):
    def broken_llm(prompt: str) -> str:
        raise RuntimeError("provider down")

    answer = ask(corpus, "What were Laptops sales in Q1?", llm=broken_llm)
    assert not answer.refused and "120" in answer.answer
    assert any("LLM call failed" in warning for warning in answer.warnings)
