"""Layout bounding boxes and reading order from a saved DoclingDocument JSON.

Pure Python: it reads `<doc_id>.docling.json` (written by engine.convert) and needs no Docling.

Every layout item (paragraph, heading, table, figure, caption, ...) becomes a `Box` with
  * the page number,
  * the label given by Docling's layout model,
  * the rectangle in PDF points, origin at the TOP-LEFT (Docling may store BOTTOMLEFT: converted here),
  * `order`: position in the reading order (depth-first walk of `body`, the order Docling recovered).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

COLLECTIONS = ("texts", "tables", "pictures", "key_value_items", "form_items")


@dataclass(frozen=True)
class Box:
    page: int
    label: str
    kind: str  # texts / tables / pictures ...
    text: str
    left: float
    top: float
    right: float
    bottom: float
    order: int
    ref: str

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


def _norm_bbox(bbox: dict, page_height: float) -> tuple[float, float, float, float]:
    """Return (left, top, right, bottom) with a top-left origin."""
    l, r = float(bbox["l"]), float(bbox["r"])
    t, b = float(bbox["t"]), float(bbox["b"])
    origin = str(bbox.get("coord_origin", "TOPLEFT")).upper()
    if "BOTTOM" in origin:  # y grows upward: flip
        top, bottom = page_height - t, page_height - b
    else:
        top, bottom = t, b
    return min(l, r), min(top, bottom), max(l, r), max(top, bottom)


def _walk(node: dict, doc: dict, seen: list[str]) -> None:
    for child in node.get("children", []):
        ref = child.get("$ref") if isinstance(child, dict) else None
        if not ref:
            continue
        seen.append(ref)
        _, collection, index = ref.split("/")
        if collection in ("groups", "body"):
            group = doc.get(collection, [])[int(index)] if collection == "groups" else doc["body"]
            _walk(group, doc, seen)


def reading_order(doc: dict) -> dict[str, int]:
    """Map '#/texts/3' -> rank, following the body tree (groups are entered, not ranked)."""
    refs: list[str] = []
    _walk(doc.get("body", {}), doc, refs)
    ordered = [r for r in refs if not r.startswith("#/groups/")]
    return {ref: rank for rank, ref in enumerate(ordered)}


def page_sizes(doc: dict) -> dict[int, tuple[float, float]]:
    sizes = {}
    for key, page in (doc.get("pages") or {}).items():
        size = page.get("size") or {}
        sizes[int(page.get("page_no", key))] = (float(size.get("width", 0)), float(size.get("height", 0)))
    return sizes


def load_boxes(docling_json: str | Path | dict) -> list[Box]:
    """All layout boxes of a document, sorted by (page, reading order)."""
    doc = docling_json if isinstance(docling_json, dict) else json.loads(
        Path(docling_json).read_text(encoding="utf-8")
    )
    sizes = page_sizes(doc)
    ranks = reading_order(doc)
    boxes: list[Box] = []
    for collection in COLLECTIONS:
        for index, item in enumerate(doc.get(collection, [])):
            ref = f"#/{collection}/{index}"
            label = str(item.get("label", collection[:-1]))
            text = str(item.get("text", "") or "")
            if collection == "tables" and not text:
                text = f"table {item.get('data', {}).get('num_rows', '?')}x{item.get('data', {}).get('num_cols', '?')}"
            for prov in item.get("prov", []):
                page = int(prov["page_no"])
                _, height = sizes.get(page, (0.0, 0.0))
                l, t, r, b = _norm_bbox(prov["bbox"], height)
                boxes.append(Box(page, label, collection, text, l, t, r, b,
                                 ranks.get(ref, 10**6 + index), ref))
    return sorted(boxes, key=lambda x: (x.page, x.order))


def boxes_for_page(boxes: list[Box], page: int, labels: set[str] | None = None) -> list[Box]:
    return [b for b in boxes if b.page == page and (labels is None or b.label in labels)]


def label_counts(boxes: list[Box]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in boxes:
        counts[b.label] = counts.get(b.label, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
