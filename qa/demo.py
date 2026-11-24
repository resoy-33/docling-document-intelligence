"""Command-line demo (no server needed).

    python -m qa.demo --root demo/docs --question "What were Laptops sales in Q1?"
    python -m qa.demo --root demo/docs --list
    python -m qa.demo --root output --question "What is the grand total?" --doc-id report1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import QAService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grounded Q&A over validated tables")
    parser.add_argument("--root", default="demo/docs", help="engine output folder")
    parser.add_argument("--question", "-q", help="question to ask")
    parser.add_argument("--doc-id", help="restrict the answer to one document")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--list", action="store_true", help="list documents and tables")
    parser.add_argument("--no-hybrid", action="store_true", help="force the Markdown fallback")
    args = parser.parse_args(argv)

    service = QAService(
        Path(args.root), prefer_hybrid=not args.no_hybrid
    )
    if args.list or not args.question:
        print(json.dumps(
            {
                "stats": service.stats(),
                "documents": [document.model_dump() for document in service.documents()],
            },
            indent=2,
            ensure_ascii=False,
        ))
        if not args.question:
            return 0

    answer = service.ask(args.question, doc_id=args.doc_id, top_k=args.top_k)
    print(json.dumps(answer.model_dump(), indent=2, ensure_ascii=False))
    return 0 if not answer.refused else 3


if __name__ == "__main__":
    raise SystemExit(main())
