"""Count the tables each extractor found, per PDF, and write a small Markdown report.

    python -m baseline.compare_report                      # uses samples/, output/, output_baseline/

It only COUNTS tables (found vs. not found). Whether a table is CORRECT is decided by the
verification harness (harness). Run it after:
    python -m engine.convert samples --out output
    python -m baseline.compare_pdfplumber samples --out output_baseline
"""
import argparse
from pathlib import Path


def count_tables(root: Path, doc_id: str) -> int | None:
    """Number of table JSON files for a PDF, or None if that PDF was never processed."""
    folder = root / doc_id / "tables"
    if not folder.exists():
        return None
    return len(list(folder.glob("*.json")))


def build_report(samples: Path, docling_dir: Path, baseline_dir: Path) -> str:
    lines = [
        "| PDF | Tables found by Docling | Tables found by pdfplumber |",
        "| --- | --- | --- |",
    ]
    for pdf in sorted(samples.glob("*.pdf")):
        a = count_tables(docling_dir, pdf.stem)
        b = count_tables(baseline_dir, pdf.stem)
        fmt = lambda n: "not run" if n is None else str(n)  # noqa: E731
        lines.append(f"| `{pdf.name}` | {fmt(a)} | {fmt(b)} |")
    lines.append("")
    lines.append("This counts tables found, not whether they are correct.")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="samples")
    ap.add_argument("--docling", default="output")
    ap.add_argument("--baseline", default="output_baseline")
    ap.add_argument("--out", default="comparison_report.md")
    args = ap.parse_args()
    report = build_report(Path(args.samples), Path(args.docling), Path(args.baseline))
    Path(args.out).write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n(saved to {args.out})")


if __name__ == "__main__":
    main()
