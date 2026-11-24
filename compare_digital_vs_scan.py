import time
from pathlib import Path
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

def make_converter(ocr: bool):
    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.do_ocr = ocr
    if ocr:
        opts.ocr_options.force_full_page_ocr = True   # ignore any text layer, OCR the whole page
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})

jobs = [("digital", "samples/invoice_zoho.pdf", False),
        ("scan",    "samples/scan_invoice.pdf", True)]

Path("output_compare").mkdir(exist_ok=True)
for name, path, ocr in jobs:
    start = time.time()
    doc = make_converter(ocr).convert(path).document
    print(f"\n=== {name}  (ocr={ocr})  {time.time() - start:.1f}s  tables={len(doc.tables)} ===")
    Path(f"output_compare/{name}.md").write_text(doc.export_to_markdown(), encoding="utf-8")
    for i, table in enumerate(doc.tables):
        df = table.export_to_dataframe(doc=doc)
        df.to_csv(f"output_compare/{name}_table{i + 1}.csv", index=False)
        print(df.to_string())