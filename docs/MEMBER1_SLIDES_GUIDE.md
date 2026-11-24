# Member 1 - slides guide

Rule from the professor: zero forcing, zero hallucinations, zero falsifications.
Every command must be run by you, and every claim needs a source link.

## Official source

Docling repository: https://github.com/docling-project/docling (README confirmed, version 2.151.1: advanced PDF
understanding incl. page layout, reading order and table structure; unified `DoclingDocument` format; export to
Markdown, HTML and lossless JSON; OCR for scanned PDFs; CLI; MIT license; Python 3.10 or newer).
Not yet read by the team: the official documentation (https://docling-project.github.io/docling/) and the technical
paper (https://arxiv.org/abs/2408.09869). Check TableFormer and pipeline details there before writing them.

## Slides (about 6-7)

| # | Slide | Content | Evidence to collect |
|---|---|---|---|
| 1 | What is Docling | Definition in your own words, with the repo link | Link |
| 2 | Architecture (your own diagram) | Stages as described in the docs and paper, after you checked them | Draw it yourselves |
| 3 | DoclingDocument and exports | Markdown, JSON, HTML (confirmed in the README) | Screenshot of a `.md` and a `.docling.json` |
| 4 | Installation | `pip install docling`, `docling --version` | Screenshot |
| 5 | CLI | `docling convert samples/sample_simple_table.pdf --to md --output cli_output`, then `--table-mode accurate` | Screenshot |
| 6 | Python API | `DocumentConverter`, `doc.tables`, `export_to_dataframe(doc=doc)` (see `engine/convert.py`) | Table JSON next to the PDF |
| 7 | Comparison matrix | see below | Your own run + links |

## Real results to show (your own runs)

- `python -m baseline.compare_report` after both extractors ran (or `run_all.bat`): tables found per PDF.
- The failure case: `sample_wrong_total_long_title.pdf` gave 0 tables, `sample_wrong_total.pdf` gave 1.
  Say it as it is: the cause is not established.
- The checksum pass rate for both tools, from Member 2's validator.

## Comparison matrix template

| Criterion | Docling | pdfplumber | How to fill it honestly |
|---|---|---|---|
| Tables found per PDF | `baseline/compare_report.py` | `baseline/compare_report.py` | from your run |
| Checksum pass rate | validator on `output/` | validator on `output_baseline/` | needs Member 2 |
| Multi-column reading order | read the `.md` of `sample_two_column_table` | compare by eye | quote only what you saw |
| Scanned PDFs / OCR | `--ocr` option exists in the CLI | check the pdfplumber docs | test with a scanned PDF, cite the docs |
| Speed | `seconds` in `summary.json` | time the script | same machine, same PDFs |
| License | MIT (README) | check its repository | link each one |

Leave a cell empty rather than guess. Add 2-3 harder PDFs to `samples/` (no borders, merged header cells, a scan)
and rerun both tools: the clean samples cannot separate the two.

## Likely Q&A

- Why does layout analysis matter on two-column pages?
- What does TableFormer do that a ruling-line detector cannot?
- What does a `DoclingDocument` contain, and how do you get a DataFrame from it?
- `--table-mode fast` vs `accurate`?
- Why a common JSON contract, and who consumes it?
- Why did one PDF give 0 tables, and what does the harness do about it?
