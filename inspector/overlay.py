"""Render a PDF page (or a scanned image) and draw Docling's layout boxes on it (no Docling needed)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from engine.boxes import Box

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
PREVIEW_SUFFIXES = {".pdf"} | IMAGE_SUFFIXES  # formats that have a page picture to draw on

LABEL_COLORS = {
    "table": "#d62728", "section_header": "#1f77b4", "title": "#1f77b4", "text": "#2ca02c",
    "paragraph": "#2ca02c", "list_item": "#17becf", "picture": "#9467bd", "caption": "#ff7f0e",
    "page_header": "#7f7f7f", "page_footer": "#7f7f7f", "footnote": "#8c564b", "formula": "#e377c2",
}
DEFAULT_COLOR = "#bcbd22"


def color_for(label: str) -> str:
    return LABEL_COLORS.get(label, DEFAULT_COLOR)


def render_page(
    pdf_path: str | Path,
    page: int,
    scale: float = 1.5,
    page_size: tuple[float, float] | None = None,
) -> Image.Image:
    """Rasterize page `page` (1-based) of a PDF, or open a scanned image.

    For an image, `page_size` is the (width, height) Docling stored for the page, in points.
    The picture is resized to that size * scale so the boxes land in the right place.
    """
    if Path(pdf_path).suffix.lower() in IMAGE_SUFFIXES:
        image = Image.open(pdf_path).convert("RGB")
        if page_size and page_size[0] > 0 and page_size[1] > 0:
            image = image.resize((round(page_size[0] * scale), round(page_size[1] * scale)))
        return image

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return pdf[page - 1].render(scale=scale).to_pil().convert("RGB")
    finally:
        pdf.close()


def draw_boxes(image: Image.Image, boxes: list[Box], scale: float, show_order: bool = True) -> Image.Image:
    """Draw each box (PDF points, top-left origin) on a copy of the page image."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    for box in boxes:
        color = color_for(box.label)
        rect = [box.left * scale, box.top * scale, box.right * scale, box.bottom * scale]
        draw.rectangle(rect, outline=color, width=2)
        tag = f"{box.order + 1} {box.label}" if show_order and box.order < 10**6 else box.label
        x, y = rect[0], max(rect[1] - 12, 0)
        draw.rectangle([x, y, x + 6 * len(tag) + 4, y + 12], fill=color)
        draw.text((x + 2, y), tag, fill="white")
    return out
