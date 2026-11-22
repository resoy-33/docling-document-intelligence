"""Load an engine output folder into the objects used by retrieval and Q&A.

Expected layout (written by Member 1, validated by Member 2):

    output/<doc_id>/summary.json
    output/<doc_id>/<doc_id>.md
    output/<doc_id>/<doc_id>.docling.json      (optional, HybridChunker source)
    output/<doc_id>/tables/<table_id>.json     (team contract)

Verdicts are recomputed from the table JSON with the harness, never read from a saved
report.  The corpus also keeps document-level issues (0 tables, failed extraction), so
the API can explain *why* it refuses instead of silently returning nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from harness.checks import DEFAULT_TOL
from harness.models import TableResult
from harness.validate import load_table

from .chunking import chunk_document
from .models import Chunk, DocumentInfo, TableVerdict
from .retrieval import BM25Index
from .verdicts import verdict_for_file


@dataclass(frozen=True)
class TableContext:
    """A validated table and its verdict (everything the answerer needs)."""

    table: TableResult
    verdict: TableVerdict

    @property
    def passed(self) -> bool:
        return self.verdict.passed


@dataclass
class Corpus:
    root: Path
    documents: dict[str, DocumentInfo] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)
    chunks_by_doc: dict[str, list[Chunk]] = field(default_factory=dict)
    table_contexts: dict[str, TableContext] = field(default_factory=dict)
    index: BM25Index = field(default_factory=lambda: BM25Index([]))

    def contexts(self, doc_id: str | None = None) -> list[TableContext]:
        if doc_id:
            return [ctx for ctx in self.table_contexts.values() if ctx.table.doc_id == doc_id]
        return list(self.table_contexts.values())

    def get_table(self, table_id: str) -> TableContext | None:
        return self.table_contexts.get(table_id)

    @property
    def n_tables(self) -> int:
        return len(self.table_contexts)

    @property
    def n_passed(self) -> int:
        return sum(1 for ctx in self.table_contexts.values() if ctx.passed)

    @property
    def chunking_methods(self) -> dict[str, str]:
        return {doc_id: info.chunking_method for doc_id, info in self.documents.items()}


def _read_summary(doc_dir: Path) -> dict:
    path = doc_dir / "summary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _status(value) -> Literal["ok", "no_tables", "failed", "unknown"]:
    return value if value in ("ok", "no_tables", "failed") else "unknown"


def load_corpus(
    root: str | Path,
    prefer_hybrid: bool = True,
    tokenizer: str | None = None,
    tol: float = DEFAULT_TOL,
    require_totals: bool = False,
    hybrid_max_tokens: int = 512,
) -> Corpus:
    """Scan `root` and build the full corpus.  Missing root -> empty corpus."""
    root = Path(root)
    corpus = Corpus(root=root)
    if not root.is_dir():
        return corpus

    for doc_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        tables_dir = doc_dir / "tables"
        summary_path = doc_dir / "summary.json"
        if not tables_dir.is_dir() and not summary_path.exists():
            continue  # not an engine output folder

        info = _read_summary(doc_dir)
        doc_id = doc_dir.name
        tables: list[TableResult] = []
        verdicts: list[TableVerdict] = []
        notes: list[str] = []

        if tables_dir.is_dir():
            for table_path in sorted(tables_dir.glob("*.json")):
                verdict = verdict_for_file(
                    table_path, tol=tol, require_totals=require_totals
                )
                if verdict.doc_id != doc_id:
                    # Keep the folder name authoritative; the contract file should match.
                    notes.append(
                        f"table {verdict.table_id}: doc_id {verdict.doc_id!r} "
                        f"differs from folder {doc_id!r}"
                    )
                verdicts.append(verdict)
                try:
                    table = load_table(table_path)
                except (OSError, ValueError):
                    notes.append(f"table file {table_path.name} is not a valid contract table")
                    continue
                tables.append(table)
                existing = corpus.table_contexts.get(table.table_id)
                if existing is None:
                    corpus.table_contexts[table.table_id] = TableContext(table, verdict)
                else:
                    notes.append(f"duplicate table_id {table.table_id!r}: kept the first file")

        verdict_map = {verdict.table_id: verdict for verdict in verdicts}
        chunks, method = chunk_document(
            doc_dir,
            tables,
            verdict_map,
            prefer_hybrid=prefer_hybrid,
            max_tokens=hybrid_max_tokens,
            tokenizer=tokenizer,
        )
        corpus.chunks.extend(chunks)
        corpus.chunks_by_doc[doc_id] = chunks

        status = _status(info.get("status"))
        if status == "unknown" and tables:
            status = "ok"
        issue = ""
        if status == "failed":
            issue = f"extraction failed: {info.get('error') or 'unknown error'}"
        elif not tables:
            issue = "0 tables found (a table was expected: treated as a failure)"
        if notes:
            issue = "; ".join([issue, *notes]) if issue else "; ".join(notes)

        n_passed = sum(1 for verdict in verdicts if verdict.passed)
        info_obj = DocumentInfo(
            doc_id=doc_id,
            status=status,
            source=info.get("source"),
            n_tables=len(tables),
            n_passed=n_passed,
            pass_rate_tables=(round(n_passed / len(tables), 4) if tables else None),
            issue=issue,
            chunking_method=method,
            tables=tables,
            verdicts=verdicts,
        )
        corpus.documents[doc_id] = info_obj

    corpus.index = BM25Index(corpus.chunks)
    return corpus


def empty_corpus(root: str | Path) -> Corpus:
    """Convenience for tests and for an API started before any conversion."""
    return Corpus(root=Path(root), index=BM25Index([]))
