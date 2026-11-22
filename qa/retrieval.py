"""Deterministic lexical retrieval (BM25) used by the grounded answerer.

Why BM25 and not embeddings by default?
  * it runs offline, with no model download and no API key;
  * it is deterministic, so a test can assert the exact evidence used;
  * table questions are mostly lexical ("Laptops", "Q1", "total"), which BM25 handles well.

The retrieval interface is deliberately small.  An embedding backend can be added later
without touching the answerer; the RAG theory on the slides explains both options.
Reference: Robertson & Zaragoza, "The Probabilistic Relevance Framework: BM25 and Beyond"
(2009), https://doi.org/10.1561/1500000019
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from .models import Chunk, RetrievedChunk

_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "did", "do",
    "does", "for", "from", "had", "has", "have", "how", "i", "if", "in", "into",
    "is", "it", "its", "me", "my", "of", "on", "or", "our", "please", "show",
    "tell", "that", "the", "their", "them", "then", "there", "these", "this",
    "to", "was", "we", "were", "what", "when", "where", "which", "who", "why",
    "will", "with", "would", "you", "your",
    # French question words (the harness already accepts French total labels)
    "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du", "en", "est",
    "et", "la", "le", "les", "ou", "par", "pas", "pour", "quel", "quelle",
    "quels", "quelles", "qui", "sur", "un", "une",
}


def fold(text: str) -> str:
    """Lowercase and remove accents so 'Catégorie' matches 'categorie'."""
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def stem(token: str) -> str:
    """Very small, documented plural folding.  It is not a linguistic stemmer."""
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    """Tokens used both for indexing and for querying (same function on both sides)."""
    tokens = [stem(token) for token in _WORD.findall(fold(text))]
    if keep_stopwords:
        return tokens
    return [token for token in tokens if token not in STOPWORDS]


class BM25Index:
    """A small, dependency-free BM25 index over `Chunk` objects."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = list(chunks)
        self.k1 = k1
        self.b = b
        self.doc_tokens: list[list[str]] = [tokenize(chunk.text) for chunk in self.chunks]
        self.doc_len = [len(tokens) for tokens in self.doc_tokens]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.term_freqs = [Counter(tokens) for tokens in self.doc_tokens]
        doc_freq: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            doc_freq.update(set(tokens))
        n_docs = len(self.chunks)
        self.idf = {
            term: math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def search(
        self,
        query: str,
        top_k: int = 5,
        doc_id: str | None = None,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.chunks:
            return []
        results: list[RetrievedChunk] = []
        for index, chunk in enumerate(self.chunks):
            if doc_id and chunk.doc_id != doc_id:
                continue
            freqs = self.term_freqs[index]
            length = self.doc_len[index] or 1
            score = 0.0
            for term in query_tokens:
                frequency = freqs.get(term, 0)
                if not frequency:
                    continue
                idf = self.idf.get(term, 0.0)
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * length / (self.avg_len or 1)
                )
                score += idf * (frequency * (self.k1 + 1)) / denominator
            if score <= min_score:
                continue
            # A table chunk carries the row labels and column headers in one place, which
            # is exactly what numeric questions need.  This small boost breaks ties in
            # favour of structured evidence, never in favour of a failed table.
            if chunk.kind == "table":
                score *= 1.10
            results.append(RetrievedChunk(chunk=chunk, score=round(score, 6)))
        results.sort(key=lambda item: (-item.score, item.chunk.order, item.chunk.chunk_id))
        for rank, item in enumerate(results[:top_k], start=1):
            item.rank = rank
        return results[:top_k]
