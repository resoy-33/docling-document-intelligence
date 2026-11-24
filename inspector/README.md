# Inspector

`streamlit run inspector/app.py` (or `run_inspector.bat`). Reads `output/<doc_id>/` (or `DOCLING_OUTPUT_DIR`).

* **Sidebar**: upload a PDF, DOCX or scanned image (PPTX, XLSX and HTML also work) and click
  **Convert with Docling** (options: force OCR, accurate table mode). The file is saved in `uploads/` and
  converted ONLY when the button is clicked. Then pick any converted document.
* **Dashboard**: status, pages, tables, number of PASS / FLAGGED tables, plus an overview of all documents.
* **Page & layout boxes**: the rendered PDF page (or scanned image) with Docling's layout boxes coloured by
  label and numbered in reading order, and the list of layout items.
* **Tables & validation**: every table with its verdict explained in plain words, CSV / JSON / Markdown
  per table and one Excel workbook per document.
* **Markdown**: the whole document exported by Docling (rendered or source), downloadable.
* **Ask a question**: grounded Q&A on this document; a FLAGGED table is never used (refusal with the reason).
* **Conversion details**: retry cascade attempts, mode, time, warnings.

Logic lives in `engine/boxes.py` (boxes, reading order), `inspector/overlay.py` (drawing) and
`engine/export.py` (downloads); all are tested without Docling. DOCX / PPTX / XLSX / HTML have no page
image, so no boxes are drawn for them (their tables are still shown).
