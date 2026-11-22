"""Chunking for Member 3.

Two strategies, chosen automatically:

1. **HybridChunker (primary).**  When Docling is installed and the engine wrote
   `<doc_id>.docling.json`, we reload the `DoclingDocument` and use
   `docling.chunking.HybridChunker`.  This is the strategy required by the project.
2. **Markdown/table fallback (deterministic, no models).**  When Docling is not installed
   (light local setup, CI) or the Docling JSON cannot be reloaded, we build chunks from
   the Markdown export plus one chunk per contract table.  The fallback is clearly
   labelled with `chunking_method="markdown"` so nobody can mistake it for HybridChunker.

Every chunk carries `page`, `table_id` and `validation_status`.  Table chunks also carry
the structured columns/rows, so answers are computed from the validated table, never by
parsing Markdown.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from harness.models import TableResult

from .models import Cell, Chunk, TableVerdict, ValidationStatus

PAGE_MARKER = re.compile(r"^\s*<!--\s*page\s*[:=]?\s*(\d+)\s*-->\s*$", re.IGNORECASE)
_TABLE_LINE = re.compile(r"^\s*\|")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


# --------------------------------------------------------------------- helpers
def _status_for(table_id: str, verdicts: dict[str, TableVerdict]) -> ValidationStatus:
    verdict = verdicts.get(table_id)
    if verdict is None:
        return ValidationStatus.UNKNOWN
    return ValidationStatus.PASSED if verdict.passed else ValidationStatus.FAILED


def _fmt(value: Cell) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def table_markdown(table: TableResult) -> str:
    """Render a contract table as Markdown (used in chunk text and evidence)."""
    header = "| " + " | ".join(table.columns) + " |"
    sep = "| " + " | ".join("---" for _ in table.columns) + " |"
    lines = [header, sep]
    for row in table.rows:
        lines.append("| " + " | ".join(_fmt(cell) for cell in row) + " |")
    return "\n".join(lines)


def table_text(table: TableResult, status: ValidationStatus, part: int = 1, n_parts: int = 1) -> str:
    """Text used by retrieval for a table chunk.  It repeats row labels and headers."""
    where = f"page {table.page}" if table.page else "page unknown"
    part_note = f" (part {part}/{n_parts})" if n_parts > 1 else ""
    return (
        f"Table {table.table_id} of document {table.doc_id}, {where}{part_note}. "
        f"Validation status: {status.value}.\n"
        f"Columns: {' | '.join(table.columns)}\n"
        f"{table_markdown(table)}"
    )


def make_table_chunks(
    table: TableResult,
    status: ValidationStatus,
    max_rows_per_chunk: int = 40,
    order_start: int = 0,
) -> list[Chunk]:
    """One chunk per table, split only when a table is very long.

    Splitting keeps the same `table_id`; the answerer still loads the full table from the
    contract JSON, so aggregation is never computed on a fragment.
    """
    rows = table.rows or []
    if not rows:
        return []
    limit = max(1, max_rows_per_chunk)
    groups = [rows[i : i + limit] for i in range(0, len(rows), limit)]
    chunks: list[Chunk] = []
    n_parts = len(groups)
    for index, group in enumerate(groups, start=1):
        part_table = table.model_copy(update={"rows": group})
        chunk_id = f"{table.doc_id}:table:{table.table_id}"
        if n_parts > 1:
            chunk_id += f":part{index}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=table.doc_id,
                text=table_text(part_table, status, part=index, n_parts=n_parts),
                page=table.page,
                table_id=table.table_id,
                kind="table",
                validation_status=status,
                table_columns=list(table.columns),
                table_rows=[[cell for cell in row] for row in group],
                part=index,
                n_parts=n_parts,
                order=order_start + index - 1,
            )
        )
    return chunks


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split a paragraph on word boundaries without dropping any word."""
    if len(text) <= max_chars:
        return [text]
    words = text.split()
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and size + extra > max_chars:
            pieces.append(" ".join(current))
            current, size = [word], len(word)
        else:
            current.append(word)
            size += extra
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_markdown(
    markdown: str,
    doc_id: str,
    tables: list[TableResult] | None = None,
    verdicts: dict[str, TableVerdict] | None = None,
    max_chars: int = 1000,
    max_rows_per_chunk: int = 40,
) -> list[Chunk]:
    """Deterministic fallback chunker over the Markdown export.

    Page numbers are read from `<!-- page: N -->` markers when present.  Docling's default
    Markdown export does not contain them, so `page` stays `None` for text chunks in that
    case; table chunks always take the page from the contract JSON.  We never invent one.
    """
    tables = tables or []
    verdicts = verdicts or {}
    chunks: list[Chunk] = []
    order = 0
    page: int | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal order, buffer
        text = "\n\n".join(part.strip() for part in buffer if part.strip()).strip()
        buffer = []
        if not text:
            return
        for piece in _split_long(text, max_chars):
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}:text:{order + 1:04d}",
                    doc_id=doc_id,
                    text=piece,
                    page=page,
                    kind="text",
                    validation_status=ValidationStatus.NOT_APPLICABLE,
                    order=order,
                )
            )
            order += 1

    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            buffer.append("\n".join(paragraph))
            paragraph = []

    for raw_line in (markdown or "").splitlines():
        line = raw_line.rstrip()
        marker = PAGE_MARKER.match(line)
        if marker:
            flush_paragraph()
            flush()
            page = int(marker.group(1))
            continue
        if _TABLE_LINE.match(line) or _TABLE_SEP.match(line):
            # Tables are represented by dedicated table chunks (structured data).
            continue
        if not line.strip():
            flush_paragraph()
            continue
        paragraph.append(line)

    flush_paragraph()
    flush()

    for table in sorted(tables, key=lambda t: (t.page, t.table_id)):
        status = _status_for(table.table_id, verdicts)
        made = make_table_chunks(
            table, status, max_rows_per_chunk=max_rows_per_chunk, order_start=order
        )
        chunks.extend(made)
        order += len(made)
    return chunks


# ------------------------------------------------------------------ HybridChunker
def _load_docling_document(path: Path):
    """Reload a DoclingDocument written by `doc.export_to_dict()`.

    `DoclingDocument` is a Pydantic v2 model; `model_validate_json` is the stable entry
    point.  We keep a JSON-dict fallback for older docling-core versions.
    """
    from docling_core.types.doc import DoclingDocument  # type: ignore

    text = path.read_text(encoding="utf-8")
    try:
        return DoclingDocument.model_validate_json(text)
    except Exception:
        return DoclingDocument.model_validate(json.loads(text))


def _docling_table_map(doc, doc_id: str) -> dict[str, str]:
    """Map Docling `self_ref` (e.g. '#/tables/0') to the engine's table_id.

    The engine numbers tables per page in document order, so re-walking `doc.tables`
    reproduces exactly the same ids as `engine.convert.extract_tables`.
    """
    mapping: dict[str, str] = {}
    per_page: dict[int, int] = {}
    for table in getattr(doc, "tables", []):
        prov = getattr(table, "prov", None) or []
        page = getattr(prov[0], "page_no", 0) if prov else 0
        per_page[page] = per_page.get(page, 0) + 1
        self_ref = getattr(table, "self_ref", None)
        if self_ref:
            mapping[self_ref] = f"{doc_id}_p{page}_t{per_page[page]}"
    return mapping


def chunk_with_hybrid(
    docling_json: Path,
    doc_id: str,
    tables: list[TableResult],
    verdicts: dict[str, TableVerdict],
    max_tokens: int = 512,
    tokenizer: str | None = None,
) -> list[Chunk]:
    """Chunk a DoclingDocument with HybridChunker (the project's required strategy)."""
    from docling.chunking import HybridChunker  # type: ignore

    doc = _load_docling_document(Path(docling_json))
    table_by_id = {table.table_id: table for table in tables}
    ref_to_id = _docling_table_map(doc, doc_id)

    kwargs: dict = {"max_tokens": max_tokens}
    if tokenizer:
        kwargs["tokenizer"] = tokenizer
    chunker = HybridChunker(**kwargs)

    chunks: list[Chunk] = []
    for index, item in enumerate(chunker.chunk(dl_doc=doc)):
        text = getattr(item, "text", "") or ""
        if not text.strip():
            continue
        meta = getattr(item, "meta", None)
        doc_items = list(getattr(meta, "doc_items", []) or [])
        pages = [
            prov.page_no
            for doc_item in doc_items
            for prov in (getattr(doc_item, "prov", None) or [])
            if getattr(prov, "page_no", None)
        ]
        page = min(pages) if pages else None
        table_ids: list[str] = []
        for doc_item in doc_items:
            table_id = ref_to_id.get(getattr(doc_item, "self_ref", ""))
            if table_id and table_id not in table_ids:
                table_ids.append(table_id)
        table_id = table_ids[0] if table_ids else None
        table = table_by_id.get(table_id) if table_id else None
        status = (
            _status_for(table_id, verdicts) if table_id else ValidationStatus.NOT_APPLICABLE
        )
        headings = list(getattr(meta, "headings", []) or [])
        if headings:
            text = " / ".join(str(h) for h in headings) + "\n" + text
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}:hybrid:{index:04d}",
                doc_id=doc_id,
                text=text,
                page=page,
                table_id=table_id,
                kind="table" if table_id else "text",
                validation_status=status,
                table_columns=list(table.columns) if table else [],
                table_rows=[[cell for cell in row] for row in table.rows] if table else [],
                order=index,
            )
        )

    # HybridChunker can merge a small table into a paragraph, or skip one entirely.
    # Guarantee that every contract table has a structured table chunk.
    covered = {chunk.table_id for chunk in chunks if chunk.table_id}
    order = len(chunks)
    for table in sorted(tables, key=lambda t: (t.page, t.table_id)):
        if table.table_id not in covered:
            made = make_table_chunks(
                table, _status_for(table.table_id, verdicts), order_start=order
            )
            chunks.extend(made)
            order += len(made)
    return chunks


def chunk_document(
    doc_dir: Path,
    tables: list[TableResult],
    verdicts: dict[str, TableVerdict],
    prefer_hybrid: bool = True,
    max_tokens: int = 512,
    tokenizer: str | None = None,
) -> tuple[list[Chunk], str]:
    """Return `(chunks, method)` for one output/<doc_id>/ folder.

    `method` is `"hybrid"` or `"markdown"`, so the API and the slides can state exactly
    which strategy ran on which machine.
    """
    doc_dir = Path(doc_dir)
    doc_id = doc_dir.name
    docling_json = doc_dir / f"{doc_id}.docling.json"
    markdown_path = doc_dir / f"{doc_id}.md"

    if prefer_hybrid and docling_json.exists():
        try:
            chunks = chunk_with_hybrid(
                docling_json, doc_id, tables, verdicts,
                max_tokens=max_tokens, tokenizer=tokenizer,
            )
            if chunks:
                return chunks, "hybrid"
        except Exception as exc:  # docling not installed, old JSON, tokenizer download...
            fallback_note = f"markdown (hybrid failed: {type(exc).__name__})"
        else:
            fallback_note = "markdown (hybrid returned no chunks)"
    else:
        fallback_note = "markdown"

    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
    chunks = chunk_markdown(markdown, doc_id, tables=tables, verdicts=verdicts)
    return chunks, fallback_note
