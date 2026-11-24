"""Baseline for the comparison matrix: extract tables with pdfplumber and write
them in the SAME contract format as the Docling engine.

    python -m baseline.compare_pdfplumber samples/ --out output_baseline

Then the validator can be run on both output/ (Docling) and
output_baseline/ (pdfplumber) to get a real, reproducible pass rate.
"""
import argparse
import json
from pathlib import Path

import pdfplumber

from engine.contract import clean_cell


def extract(pdf_path: Path, out_dir: Path) -> int:
    doc_id = pdf_path.stem
    target = out_dir / doc_id / "tables"
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for idx, raw in enumerate(page.extract_tables(), start=1):
                if not raw or len(raw) < 2:
                    continue
                header = [str(c or "").strip() for c in raw[0]]
                rows = [[clean_cell(c) for c in row] for row in raw[1:]]
                table = {
                    "doc_id": doc_id,
                    "table_id": f"{doc_id}_p{page_no}_t{idx}",
                    "page": page_no,
                    "columns": header,
                    "rows": rows,
                }
                (target / f"{table['table_id']}.json").write_text(
                    json.dumps(table, indent=2), encoding="utf-8")
                count += 1
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out", default="output_baseline")
    args = ap.parse_args()
    src = Path(args.source)
    pdfs = sorted(src.glob("*.pdf")) if src.is_dir() else [src]
    for pdf in pdfs:
        n = extract(pdf, Path(args.out))
        print(f"{pdf.name}: {n} table(s) (pdfplumber)")


if __name__ == "__main__":
    main()
