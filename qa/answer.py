"""Grounded, extractive Q&A over validated tables (Q&A layer).

The rule is simple and non-negotiable:

    A numeric answer may only be built from a table whose the harness verdict is `passed`.

The default answerer is **extractive**: it finds a cell, a row, a column or an aggregate
inside the validated table and quotes the exact cells it used.  It never invents prose
with numbers.  An optional LLM can be plugged in (`llm=` callable); its output is accepted
only if every number it contains is present in the validated table (or was computed by the
deterministic path), otherwise the deterministic answer is returned with a warning.  That
is the "harness" idea applied to generation as well as extraction.
"""
from __future__ import annotations

import math
import re
from typing import Callable

from harness.checks import find_total_col, find_total_row, is_number
from harness.models import TableResult

from .chunking import table_markdown
from .corpus import Corpus, TableContext
from .models import Answer, Citation
from .retrieval import fold, stem, tokenize

# --------------------------------------------------------------------- vocabulary
SUM_WORDS = {"sum", "total", "totals", "altogether", "combined", "add", "addition", "grand"}
AVG_WORDS = {"average", "mean", "avg"}
MAX_WORDS = {"max", "maximum", "highest", "most", "best", "top", "largest", "biggest"}
MIN_WORDS = {"min", "minimum", "lowest", "least", "worst", "smallest"}
LIST_WORDS = {"list", "show", "display", "contents", "all"}
COUNT_WORDS = {"count", "many", "number"}
COMPARE_WORDS = {"compare", "versus", "vs", "difference", "between"}
GENERIC_WORDS = {
    "table", "document", "report", "data", "say", "contain", "summary",
    "overview", "value", "values",
}
TOTAL_HEADERS = {"total", "totals", "sum", "grand total", "totale", "totaux", "somme"}

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_RAW_WORD = re.compile(r"[a-z0-9]+")
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w])")


# ----------------------------------------------------------------------- helpers
def _label_tokens(text: str) -> list[str]:
    tokens = tokenize(text)
    if tokens:
        return tokens
    return [stem(token) for token in _RAW_WORD.findall(fold(text))]


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_total_header(text: str) -> bool:
    return fold(str(text)).strip().rstrip(":") in TOTAL_HEADERS


def _month_of(text: str) -> int | None:
    for token in _label_tokens(text):
        if token in _MONTHS:
            return _MONTHS[token]
    return None


def _contains_sequence(sequence: list[str], needles: list[str]) -> bool:
    if not needles or len(needles) > len(sequence):
        return False
    for start in range(len(sequence) - len(needles) + 1):
        if sequence[start : start + len(needles)] == needles:
            return True
    return False


def _label_score(
    label: str,
    q_set: set[str],
    q_sequence: list[str],
    q_upper: set[str] | None = None,
) -> float:
    tokens = _label_tokens(label)
    if not tokens:
        return 0.0
    if len(tokens) == 1 and len(tokens[0]) == 1:
        # Single-letter row labels (fixtures use A/B) are matched only when the question
        # contains that uppercase letter as a standalone token, so "is there a total?"
        # does not accidentally select row A.
        return 1.0 if q_upper and tokens[0].upper() in q_upper else 0.0
    if _contains_sequence(q_sequence, tokens):
        return 1.0
    hits = sum(1 for token in tokens if token in q_set)
    coverage = hits / len(tokens)
    return 0.5 + 0.5 * coverage if coverage >= 0.5 else 0.0


def _match_rows(
    table: TableResult,
    q_set: set[str],
    q_sequence: list[str],
    total_row: int | None,
    q_upper: set[str] | None = None,
):
    matches = []
    for index, row in enumerate(table.rows):
        if index == total_row or not row:
            continue
        score = _label_score(str(row[0]), q_set, q_sequence, q_upper)
        if score:
            matches.append((index, score))
    matches.sort(key=lambda item: (-item[1], item[0]))
    return matches


def _match_columns(
    table: TableResult,
    q_set: set[str],
    q_sequence: list[str],
    total_col: int | None,
    include_total: bool = False,
    q_upper: set[str] | None = None,
):
    matches = []
    question_months = {_month_of(token) for token in q_set} - {None}
    for index, header in enumerate(table.columns):
        if index == 0:
            continue  # the first column is the row label, never a value column
        if not include_total and index == total_col:
            continue
        if _is_total_header(header):
            score = 1.0 if include_total and (q_set & SUM_WORDS) else 0.0
        else:
            score = _label_score(str(header), q_set, q_sequence, q_upper)
            header_month = _month_of(str(header))
            if not score and header_month and header_month in question_months:
                score = 1.0
        if score:
            matches.append((index, score))
    matches.sort(key=lambda item: (-item[1], item[0]))
    return matches


def _numeric_columns(table: TableResult, total_col: int | None) -> list[int]:
    columns = []
    for index in range(1, len(table.columns)):
        values = [
            row[index]
            for row in table.rows
            if index < len(row) and not _is_blank(row[index])
        ]
        numbers = sum(1 for value in values if is_number(value))
        if index == total_col or (values and numbers * 2 >= len(values)):
            columns.append(index)
    return columns


def _data_rows(table: TableResult, total_row: int | None) -> list[int]:
    return [index for index in range(len(table.rows)) if index != total_row]


def _fmt_number(value: float | int) -> str:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    number = float(value)
    if number.is_integer():
        return str(int(number))
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _fmt_cell(value) -> str:
    if value is None:
        return "null"
    if is_number(value):
        return _fmt_number(value)
    return str(value)


def _row_label(table: TableResult, index: int) -> str:
    row = table.rows[index]
    return str(row[0]) if row and not _is_blank(row[0]) else f"row {index + 1}"


def _row_quote(table: TableResult, index: int) -> str:
    return " | ".join(
        f"{table.columns[column]}={_fmt_cell(table.rows[index][column])}"
        for column in range(min(len(table.columns), len(table.rows[index])))
    )


def _citation(
    table: TableResult,
    row: int | None = None,
    column: int | None = None,
    quote: str | None = None,
) -> Citation:
    return Citation(
        doc_id=table.doc_id,
        table_id=table.table_id,
        page=table.page,
        row=row,
        column=table.columns[column] if column is not None and column < len(table.columns) else None,
        row_label=_row_label(table, row) if row is not None and row < len(table.rows) else None,
        quote=quote,
    )


def _source_text(citations: list[Citation]) -> str:
    locations = []
    for citation in citations:
        page = f"page {citation.page}" if citation.page else "page unknown"
        locations.append(f"{citation.doc_id}, {page}, table {citation.table_id}")
    if not locations:
        return ""
    unique = list(dict.fromkeys(locations))
    return "Source: " + "; ".join(unique) + "."


def _as_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _allowed_numbers(table: TableResult) -> set[float]:
    allowed: set[float] = set()
    for row in table.rows:
        for value in row:
            number = _as_number(value)
            if number is not None and math.isfinite(number):
                allowed.add(number)
    return allowed


def numbers_in_text(text: str) -> list[float]:
    """Numbers that a grounding check must find in the validated table."""
    values = []
    for raw in _NUMBER.findall(text or ""):
        try:
            values.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return values


def verify_grounding(text: str, allowed: set[float], abs_tol: float = 0.011) -> list[float]:
    """Return the numbers in `text` that are NOT in `allowed` (empty list = grounded)."""
    unmatched = []
    for value in numbers_in_text(text):
        if not any(math.isclose(value, candidate, abs_tol=abs_tol) for candidate in allowed):
            unmatched.append(value)
    return unmatched


def _doc_boost(doc_id: str, q_set: set[str]) -> float:
    doc_tokens = set(tokenize(doc_id.replace("_", " ")))
    return min(len(doc_tokens & q_set), 2) * 0.3


def _direct_score(
    q_set: set[str],
    q_sequence: list[str],
    table: TableResult,
    q_upper: set[str] | None = None,
) -> float:
    total_row = find_total_row(table)
    total_col = find_total_col(table)
    rows = _match_rows(table, q_set, q_sequence, total_row, q_upper)
    columns = _match_columns(table, q_set, q_sequence, total_col, q_upper=q_upper)
    score = (2.0 * rows[0][1] if rows else 0.0) + (1.5 * columns[0][1] if columns else 0.0)
    if q_set & SUM_WORDS and (total_row is not None or total_col is not None):
        score += 0.6
    if q_set & (AVG_WORDS | MAX_WORDS | MIN_WORDS):
        score += 0.3
    if q_set & LIST_WORDS:
        score += 0.2
    if q_set & COMPARE_WORDS:
        score += 0.2
    return score


# ------------------------------------------------------------------- refusals
def _refuse(
    question: str,
    reason: str,
    retrieved,
    *,
    warnings: list[str] | None = None,
    used_table_ids: list[str] | None = None,
    method: str = "extractive",
) -> Answer:
    return Answer(
        question=question,
        answer=f"I cannot answer this question. {reason}",
        grounded=False,
        refused=True,
        reason=reason,
        method=method,
        warnings=warnings or [],
        used_table_ids=used_table_ids or [],
        retrieved_chunk_ids=[hit.chunk.chunk_id for hit in retrieved],
    )


# --------------------------------------------------------------- deterministic
def _column_values(table: TableResult, column: int, data_rows: list[int]):
    return [
        (index, table.rows[index][column])
        for index in data_rows
        if column < len(table.rows[index]) and is_number(table.rows[index][column])
    ]


def _finalize(
    question: str,
    body: str,
    context: TableContext,
    citations: list[Citation],
    warnings: list[str],
    retrieved,
    *,
    extra_allowed: set[float] | None = None,
    method: str = "extractive",
) -> Answer:
    """Verify every emitted number, then add the source line.

    If the internal check fails we refuse instead of returning an ungrounded answer.
    This should be unreachable for the extractive path; it is the safety net that also
    protects the optional LLM path.
    """
    allowed = _allowed_numbers(context.table) | set(extra_allowed or ())
    unmatched = verify_grounding(body, allowed)
    if unmatched:
        reason = (
            "internal grounding check failed: the answer contained numbers that are not "
            f"in the validated table ({', '.join(_fmt_number(v) for v in unmatched)})"
        )
        return _refuse(question, reason, retrieved, warnings=warnings)
    source = _source_text(citations)
    answer = body if not source else f"{body}\n{source}"
    return Answer(
        question=question,
        answer=answer,
        grounded=True,
        refused=False,
        method=method,
        citations=citations,
        used_table_ids=[context.table.table_id],
        warnings=warnings,
        retrieved_chunk_ids=[hit.chunk.chunk_id for hit in retrieved],
    )


def _answer_from_table(
    question: str,
    q_set: set[str],
    q_sequence: list[str],
    context: TableContext,
    retrieved,
    warnings: list[str],
    q_upper: set[str] | None = None,
) -> Answer:
    table = context.table
    total_row = find_total_row(table)
    total_col = find_total_col(table)
    data_rows = _data_rows(table, total_row)
    rows = _match_rows(table, q_set, q_sequence, total_row, q_upper)
    columns = _match_columns(table, q_set, q_sequence, total_col, q_upper=q_upper)
    row = rows[0][0] if rows and rows[0][1] >= 0.5 else None
    column = columns[0][0] if columns and columns[0][1] >= 0.5 else None
    numeric_columns = _numeric_columns(table, total_col)

    wants_total = bool(q_set & SUM_WORDS)
    wants_average = bool(q_set & AVG_WORDS)
    wants_max = bool(q_set & MAX_WORDS)
    wants_min = bool(q_set & MIN_WORDS)
    wants_list = bool(q_set & LIST_WORDS)
    wants_count = bool(q_set & COUNT_WORDS)
    wants_compare = bool(q_set & COMPARE_WORDS)
    grand = "grand" in q_set or "overall" in q_set

    # 1. "how many rows / products?"
    if wants_count and ({"row", "rows", "product", "products", "item", "items"} & q_set):
        count = len(data_rows)
        body = f"The table has {count} data row{'s' if count != 1 else ''}."
        return _finalize(
            question, body, context,
            [_citation(table, quote=f"{count} data rows")],
            warnings, retrieved, extra_allowed={float(count)},
        )

    # 2. multiple row labels ("compare A and B") — before the single-row branch
    if wants_compare and len(rows) >= 2 and numeric_columns:
        target = column if column is not None else (total_col or numeric_columns[-1])
        parts = [
            f"{_row_label(table, index)}: {_fmt_cell(table.rows[index][target])}"
            for index, _ in rows
            if target < len(table.rows[index])
        ]
        body = f"Comparison ({table.columns[target]}): " + "; ".join(parts) + "."
        citations = [
            _citation(table, row=index, column=target, quote=_row_quote(table, index))
            for index, _ in rows
        ]
        return _finalize(question, body, context, citations, warnings, retrieved)

    # 3. a precise cell: row label + column header
    if row is not None and column is not None:
        value = table.rows[row][column]
        body = f"{_row_label(table, row)}, {table.columns[column]}: {_fmt_cell(value)}."
        quote = _row_quote(table, row)
        return _finalize(
            question, body, context,
            [_citation(table, row=row, column=column, quote=quote)],
            warnings, retrieved,
        )

    # 3. one row: its values, or its total
    if row is not None:
        if wants_total:
            if total_col is not None and total_col < len(table.rows[row]):
                value = table.rows[row][total_col]
                body = (
                    f"{_row_label(table, row)}, {table.columns[total_col]}: "
                    f"{_fmt_cell(value)}."
                )
                return _finalize(
                    question, body, context,
                    [_citation(table, row=row, column=total_col, quote=_row_quote(table, row))],
                    warnings, retrieved,
                )
            values = [table.rows[row][index] for index in numeric_columns if index < len(table.rows[row])]
            values = [value for value in values if is_number(value)]
            if values:
                total = math.fsum(values)
                body = (
                    f"{_row_label(table, row)}, sum of its numeric cells: "
                    f"{_fmt_number(total)}."
                )
                return _finalize(
                    question, body, context,
                    [_citation(table, row=row, quote=_row_quote(table, row))],
                    warnings, retrieved, extra_allowed={total},
                )
        parts = [
            f"{table.columns[index]}: {_fmt_cell(table.rows[row][index])}"
            for index in range(1, min(len(table.columns), len(table.rows[row])))
        ]
        body = f"{_row_label(table, row)}: " + ", ".join(parts) + "."
        return _finalize(
            question, body, context,
            [_citation(table, row=row, quote=_row_quote(table, row))],
            warnings, retrieved,
        )

    # 4. one column: average, max/min, total, or the list of values
    if column is not None:
        values = _column_values(table, column, data_rows)
        if wants_average and values:
            average = math.fsum(value for _, value in values) / len(values)
            body = (
                f"Average {table.columns[column]} across {len(values)} data rows: "
                f"{_fmt_number(average)}."
            )
            return _finalize(
                question, body, context,
                [_citation(table, column=column, quote=f"average of {len(values)} cells")],
                warnings, retrieved, extra_allowed={average, float(len(values))},
            )
        if (wants_max or wants_min) and values:
            picked = (max if wants_max else min)(values, key=lambda item: item[1])
            index, value = picked
            word = "highest" if wants_max else "lowest"
            body = (
                f"{_row_label(table, index)} has the {word} {table.columns[column]}: "
                f"{_fmt_cell(value)}."
            )
            return _finalize(
                question, body, context,
                [_citation(table, row=index, column=column, quote=_row_quote(table, index))],
                warnings, retrieved,
            )
        if wants_total:
            if total_row is not None and column < len(table.rows[total_row]) and is_number(
                table.rows[total_row][column]
            ):
                value = table.rows[total_row][column]
                body = (
                    f"{table.columns[column]} (validated Total row): {_fmt_cell(value)} "
                    f"(sum of {len(values)} data rows)."
                )
                return _finalize(
                    question, body, context,
                    [_citation(table, row=total_row, column=column, quote=_row_quote(table, total_row))],
                    warnings, retrieved, extra_allowed={float(len(values))},
                )
            total = math.fsum(value for _, value in values)
            body = (
                f"{table.columns[column]} (computed sum of {len(values)} data rows): "
                f"{_fmt_number(total)}."
            )
            return _finalize(
                question, body, context,
                [_citation(table, column=column, quote="computed from data rows")],
                warnings, retrieved, extra_allowed={total, float(len(values))},
            )
        if values:
            parts = [f"{_row_label(table, index)}: {_fmt_cell(value)}" for index, value in values]
            body = f"{table.columns[column]} by row: " + "; ".join(parts) + "."
            return _finalize(
                question, body, context,
                [_citation(table, column=column, quote="; ".join(parts))],
                warnings, retrieved,
            )

    # 5. max/min without an explicit column: use the Total column or the last numeric one
    if (wants_max or wants_min) and numeric_columns:
        target = total_col if total_col in numeric_columns else numeric_columns[-1]
        values = _column_values(table, target, data_rows)
        if values:
            index, value = (max if wants_max else min)(values, key=lambda item: item[1])
            word = "highest" if wants_max else "lowest"
            body = (
                f"{_row_label(table, index)} has the {word} {table.columns[target]}: "
                f"{_fmt_cell(value)}."
            )
            return _finalize(
                question, body, context,
                [_citation(table, row=index, column=target, quote=_row_quote(table, index))],
                warnings, retrieved,
            )

    # 6. totals: grand total, the Total row, or computed column totals
    if wants_total:
        if total_row is not None:
            if grand and total_col is not None and total_col < len(table.rows[total_row]):
                value = table.rows[total_row][total_col]
                body = f"Grand total: {_fmt_cell(value)}."
                return _finalize(
                    question, body, context,
                    [_citation(table, row=total_row, column=total_col, quote=_row_quote(table, total_row))],
                    warnings, retrieved,
                )
            parts = [
                f"{table.columns[index]}: {_fmt_cell(table.rows[total_row][index])}"
                for index in range(1, min(len(table.columns), len(table.rows[total_row])))
            ]
            body = "Total row: " + ", ".join(parts) + "."
            return _finalize(
                question, body, context,
                [_citation(table, row=total_row, quote=_row_quote(table, total_row))],
                warnings, retrieved,
            )
        if total_col is not None:
            values = _column_values(table, total_col, data_rows)
            total = math.fsum(value for _, value in values)
            body = f"Computed grand total over {len(values)} data rows: {_fmt_number(total)}."
            return _finalize(
                question, body, context,
                [_citation(table, column=total_col, quote="computed grand total")],
                warnings, retrieved, extra_allowed={total, float(len(values))},
            )
        if numeric_columns:
            parts = []
            derived = set()
            for index in numeric_columns:
                values = _column_values(table, index, data_rows)
                total = math.fsum(value for _, value in values)
                derived.add(total)
                parts.append(f"{table.columns[index]}: {_fmt_number(total)}")
            warnings.append(
                "This table has no Total row/column, so the sums were computed from the "
                "data rows; only the structure was verified by the harness."
            )
            body = "Computed totals: " + ", ".join(parts) + "."
            return _finalize(
                question, body, context,
                [_citation(table, quote="computed from data rows")],
                warnings, retrieved, extra_allowed=derived,
            )

    # 8. explicit "show/list the table", or a generic question with table evidence
    if wants_list or (not rows and not columns and (q_set & GENERIC_WORDS)):
        body = f"Table {table.table_id}:\n" + table_markdown(table)
        return _finalize(
            question, body, context,
            [_citation(table, quote=f"{len(table.rows)} rows, {len(table.columns)} columns")],
            warnings, retrieved, extra_allowed={float(len(table.rows)), float(len(table.columns))},
        )

    return _refuse(
        question,
        "no validated table cell, row or column matches this question.",
        retrieved,
        warnings=warnings,
        used_table_ids=[table.table_id],
    )


# ---------------------------------------------------------------------- public
def answer_question(
    question: str,
    corpus: Corpus,
    doc_id: str | None = None,
    top_k: int = 5,
    llm: Callable[[str], str] | None = None,
) -> Answer:
    """Answer only from validated tables; refuse with a reason otherwise."""
    question = (question or "").strip()
    if not question:
        return _refuse("", "the question is empty.", [])

    if doc_id and doc_id not in corpus.documents:
        return _refuse(
            question,
            f"unknown document id {doc_id!r}; known documents: {sorted(corpus.documents)}.",
            [],
        )

    retrieved = corpus.index.search(question, top_k=max(top_k * 4, 12), doc_id=doc_id)
    q_sequence = tokenize(question)
    q_set = set(q_sequence)
    # Single-letter row labels (A/B in the fixtures) are matched only when the question
    # contains the uppercase letter as a standalone token.
    q_upper = set(re.findall(r"(?<![\w.])[A-Z](?![\w])", question))
    contexts = corpus.contexts(doc_id)

    if not contexts:
        if doc_id:
            info = corpus.documents.get(doc_id)
            reason = info.issue if info and info.issue else "no tables were extracted for this document"
            return _refuse(question, f"{doc_id}: {reason}.", retrieved)
        return _refuse(
            question,
            "no extracted tables are available. Run the engine first, then reload the API.",
            retrieved,
        )

    scored = []
    for context in contexts:
        hits = [
            hit.score
            for hit in retrieved
            if hit.chunk.table_id == context.table.table_id
        ]
        score = (
            _direct_score(q_set, q_sequence, context.table, q_upper)
            + min(max(hits, default=0.0), 25.0) / 25.0
            + _doc_boost(context.table.doc_id, q_set)
        )
        scored.append((score, context))
    scored.sort(key=lambda item: (-item[0], not item[1].passed, item[1].table.table_id))

    best_score, best_context = scored[0]
    passed = [item for item in scored if item[1].passed]

    if not passed:
        failed = best_context
        warnings = [
            f"Table {failed.table.table_id} (page {failed.table.page}) failed verification: "
            f"{failed.verdict.reason}"
        ]
        return _refuse(
            question,
            "the only matching table(s) failed deterministic verification, so no answer "
            "can be given from them.",
            retrieved,
            warnings=warnings,
            used_table_ids=[failed.table.table_id],
        )

    best_passed_score, best_passed = passed[0]

    # A failed table that clearly matches better than every passing table is a hard stop:
    # answering from another table would silently change the subject.
    if not best_context.passed and best_score > best_passed_score + 0.05:
        warnings = [
            f"Table {best_context.table.table_id} (page {best_context.table.page}) failed "
            f"verification: {best_context.verdict.reason}"
        ]
        return _refuse(
            question,
            "the table that best matches this question failed deterministic verification; "
            "a failed table is never used to answer.",
            retrieved,
            warnings=warnings,
            used_table_ids=[best_context.table.table_id],
        )

    # Nothing lexical and nothing structural matched: do not dress up a guess as an answer.
    if best_passed_score < 0.35 and not retrieved:
        return _refuse(
            question,
            "no validated table row or column matches this question.",
            retrieved,
        )

    warnings: list[str] = []
    for score, other in scored:
        if (
            not other.passed
            and other.table.table_id != best_passed.table.table_id
            and score >= best_passed_score - 0.15
        ):
            # Only warn when the failed table is a plausible *subject*: its document is
            # named in the question, or one of its row labels matches.  Sharing a column
            # name such as "Q1" is not enough to call it a competing answer.
            failed_total_row = find_total_row(other.table)
            failed_rows = _match_rows(
                other.table, q_set, q_sequence, failed_total_row, q_upper
            )
            plausible = _doc_boost(other.table.doc_id, q_set) > 0 or (
                failed_rows and failed_rows[0][1] >= 0.5
            )
            if plausible:
                warnings.append(
                    f"Another matching table, {other.table.table_id} (page {other.table.page}), "
                    f"failed verification and was not used: {other.verdict.reason}"
                )
    if not best_passed.verdict.verifiable:
        warnings.append(
            f"Table {best_passed.table.table_id} has no Total row/column; the harness "
            "checked its structure but could not cross-check the numbers."
        )
    if doc_id:
        info = corpus.documents.get(doc_id)
        if info and info.issue:
            warnings.append(info.issue)

    deterministic = _answer_from_table(
        question, q_set, q_sequence, best_passed, retrieved, warnings, q_upper=q_upper
    )

    if llm is None or deterministic.refused:
        return deterministic

    # Optional LLM: same evidence, but every number must survive the grounding check.
    allowed = _allowed_numbers(best_passed.table) | set(numbers_in_text(deterministic.answer))
    prompt = (
        "Answer the question using ONLY the validated table below.\n"
        "Rules: quote numbers exactly as they appear; do not calculate anything that is "
        "not directly present; if the table cannot answer, reply NOT_ANSWERABLE.\n\n"
        f"Question: {question}\n\nTable {best_passed.table.table_id} "
        f"(validated, page {best_passed.table.page}):\n{table_markdown(best_passed.table)}\n"
    )
    try:
        raw = llm(prompt)
    except Exception as exc:  # noqa: BLE001 - an LLM outage must not break the API
        deterministic.warnings.append(f"LLM call failed ({type(exc).__name__}); used the extractive answer.")
        return deterministic
    if not raw or raw.strip().upper().startswith("NOT_ANSWERABLE"):
        deterministic.warnings.append("The LLM declined to answer; used the extractive answer.")
        return deterministic
    unmatched = verify_grounding(raw, allowed)
    if unmatched:
        deterministic.warnings.append(
            "LLM answer rejected by the grounding check (numbers not found in the "
            f"validated table: {', '.join(_fmt_number(v) for v in unmatched)}); "
            "used the extractive answer."
        )
        return deterministic
    return _finalize(
        question,
        raw.strip(),
        best_passed,
        deterministic.citations,
        deterministic.warnings,
        retrieved,
        extra_allowed=allowed,
        method="llm+grounding-check",
    )
