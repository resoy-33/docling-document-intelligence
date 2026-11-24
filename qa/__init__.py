"""Chunking, retrieval and grounded Q&A over validated tables.

Public entry points:

    from qa import QAService
    service = QAService("demo/docs")
    answer = service.ask("What were Laptops sales in Q1?")

The service reads the output layout written by the engine and the verdicts recomputed by
the harness.  It never answers from a table whose verdict is not `passed`.
"""
from .answer import answer_question, verify_grounding
from .corpus import Corpus, TableContext, load_corpus
from .models import Answer, Chunk, Citation, DocumentInfo, TableVerdict, ValidationStatus
from .retrieval import BM25Index, tokenize
from .service import QAService
from .verdicts import verdict_for_file, verdict_from_report

__all__ = [
    "QAService",
    "Corpus",
    "TableContext",
    "load_corpus",
    "answer_question",
    "verify_grounding",
    "BM25Index",
    "tokenize",
    "Answer",
    "Chunk",
    "Citation",
    "DocumentInfo",
    "TableVerdict",
    "ValidationStatus",
    "verdict_for_file",
    "verdict_from_report",
]
