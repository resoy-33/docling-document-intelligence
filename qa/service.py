"""Service layer used by the FastAPI app and by the CLI demo.

Keeping this outside `api/` means the Q&A logic can be tested without starting a server,
and the automation can import the service directly if it prefers Python over HTTP.
"""
from __future__ import annotations

import threading
from pathlib import Path

from harness.checks import DEFAULT_TOL

from .answer import answer_question
from .corpus import Corpus, TableContext, load_corpus
from .models import Answer, DocumentInfo


class QAService:
    """Load one engine output folder, answer questions, expose tables/documents."""

    def __init__(
        self,
        root: str | Path = "output",
        prefer_hybrid: bool = True,
        tokenizer: str | None = None,
        tol: float = DEFAULT_TOL,
        require_totals: bool = False,
    ):
        self.root = Path(root)
        self.prefer_hybrid = prefer_hybrid
        self.tokenizer = tokenizer
        self.tol = tol
        self.require_totals = require_totals
        self._lock = threading.RLock()
        self.corpus: Corpus = self._load()

    def _load(self) -> Corpus:
        return load_corpus(
            self.root,
            prefer_hybrid=self.prefer_hybrid,
            tokenizer=self.tokenizer,
            tol=self.tol,
            require_totals=self.require_totals,
        )

    def reload(self) -> Corpus:
        corpus = self._load()
        with self._lock:
            self.corpus = corpus
            return corpus

    def ask(
        self,
        question: str,
        doc_id: str | None = None,
        top_k: int = 5,
        llm=None,
    ) -> Answer:
        # Snapshot the reference; a concurrent /convert may swap the corpus.
        corpus = self.corpus
        return answer_question(question, corpus, doc_id=doc_id, top_k=top_k, llm=llm)

    def documents(self) -> list[DocumentInfo]:
        return list(self.corpus.documents.values())

    def document(self, doc_id: str) -> DocumentInfo | None:
        return self.corpus.documents.get(doc_id)

    def tables(self, doc_id: str | None = None, passed: bool | None = None) -> list[TableContext]:
        contexts = self.corpus.contexts(doc_id)
        if passed is not None:
            contexts = [context for context in contexts if context.passed is passed]
        return sorted(contexts, key=lambda context: context.table.table_id)

    def table(self, table_id: str) -> TableContext | None:
        return self.corpus.get_table(table_id)

    def stats(self) -> dict:
        return {
            "output_root": str(self.root),
            "documents": len(self.corpus.documents),
            "tables": self.corpus.n_tables,
            "tables_passed": self.corpus.n_passed,
            "chunks": len(self.corpus.chunks),
            "chunking_methods": self.corpus.chunking_methods,
        }
